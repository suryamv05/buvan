$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot

function Show-ComposeLogs {
    Write-Host '--- docker compose logs ---' -ForegroundColor Yellow
    docker compose logs --no-color --timestamps
}

try {
    Write-Host 'Removing the smoke-test stack and its volumes.' -ForegroundColor Yellow
    docker compose down -v
    if ($LASTEXITCODE -ne 0) { throw 'docker compose down -v failed.' }

    docker compose --profile workers up --build -d
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up --build -d failed.' }

    $requiredHealthy = @('postgres', 'redis', 'rabbitmq', 'minio', 'api', 'worker')
    $deadline = (Get-Date).AddMinutes(5)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        $raw = docker compose ps --all --format json
        if ($LASTEXITCODE -ne 0) { throw 'Could not inspect Compose service status.' }
        $services = @($raw -split "`r?`n" | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
        $workerLogs = docker compose logs --no-color --since 30s worker 2>&1 | Out-String
        if ($workerLogs -match '(?i)transient[_ ]excl[_ ]queues|operation queue\.declare caused a connection exception') {
            Write-Host 'Worker logs contain the RabbitMQ transient queue declaration error:' -ForegroundColor Red
            Write-Host $workerLogs
            throw 'RabbitMQ rejected the worker queue declaration.'
        }
        $failed = @($services | Where-Object {
            $_.State -eq 'restarting' -or ($_.State -eq 'exited' -and [int]$_.ExitCode -ne 0)
        })
        if ($failed.Count -gt 0) {
            foreach ($service in $failed) {
                Write-Host "Container $($service.Service) is $($service.State) (exit code $($service.ExitCode)); printing its logs now." -ForegroundColor Red
                docker compose logs --no-color --timestamps $service.Service
            }
            throw "Container failure detected: $(($failed.Service) -join ', ')."
        }
        $unhealthy = @($services | Where-Object { $_.Health -eq 'unhealthy' })
        if ($unhealthy.Count -gt 0) { throw "Unhealthy service(s): $(($unhealthy.Service) -join ', ')." }
        $migration = $services | Where-Object Service -eq 'migrate' | Select-Object -First 1
        if ($migration -and $migration.State -eq 'exited' -and [int]$migration.ExitCode -ne 0) {
            throw "Migration exited with code $($migration.ExitCode)."
        }
        $notReady = @($requiredHealthy | Where-Object {
            $serviceName = $_
            $service = $services | Where-Object Service -eq $serviceName | Select-Object -First 1
            -not $service -or $service.Health -ne 'healthy'
        })
        if ($notReady.Count -eq 0 -and $migration -and $migration.State -eq 'exited' -and [int]$migration.ExitCode -eq 0) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw 'Timed out waiting for healthy services and a successful migration exit.' }

    $health = Invoke-RestMethod -Uri 'http://localhost:8000/health' -TimeoutSec 10
    if ($health.status -ne 'ok') { throw 'The /health endpoint did not return status=ok.' }
    $readiness = Invoke-RestMethod -Uri 'http://localhost:8000/ready' -TimeoutSec 10
    if ($readiness.status -ne 'ready') { throw 'The /ready endpoint did not return status=ready.' }

    $suffix = [guid]::NewGuid().ToString('N')
    $email = "smoke-$suffix@example.com"
    $password = "Smoke-$suffix`_Pass9!"
    $body = @{ email = $email; password = $password } | ConvertTo-Json
    $registered = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/auth/register' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 10
    if (-not $registered.message) { throw 'Registration did not return the expected generic response.' }
    $tokens = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/auth/login' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 10
    if (-not $tokens.access_token -or -not $tokens.refresh_token) { throw 'Login did not return both tokens.' }

    Write-Host 'Smoke test passed: migration, service health, API readiness, registration, and login.' -ForegroundColor Green
} catch {
    Write-Host "Smoke test failed: $($_.Exception.Message)" -ForegroundColor Red
    Show-ComposeLogs
    exit 1
} finally {
    Pop-Location
}
