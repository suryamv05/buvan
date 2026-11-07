$ErrorActionPreference = 'Continue'
$script:Failures = 0

function Fail([string]$Message, [string]$Fix) {
    Write-Host "FAIL: $Message" -ForegroundColor Red
    Write-Host "      Fix: $Fix" -ForegroundColor Yellow
    $script:Failures++
}

function Pass([string]$Message) {
    Write-Host "OK:   $Message" -ForegroundColor Green
}

try {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker daemon is unreachable.' }
    Pass 'Docker Desktop engine is running.'
} catch {
    Fail 'Docker is not running.' 'Start Docker Desktop with Linux containers enabled, then rerun scripts/doctor.ps1.'
}

$envPath = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    Fail '.env is missing.' 'Copy .env.example to .env, replace every placeholder with unique 64-character hexadecimal values, then rerun this check.'
    $envValues = @{}
} else {
    Pass '.env exists.'
    $envValues = @{}
    foreach ($line in Get-Content -LiteralPath $envPath) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$' -and $Matches[1] -notmatch '^\s*#') {
            $envValues[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
    $placeholders = @($envValues.GetEnumerator() | Where-Object { $_.Value -match '(?i)REPLACE_WITH' } | ForEach-Object { $_.Key })
    if ($placeholders.Count -gt 0) {
        Fail "Placeholder values remain for: $($placeholders -join ', ')." 'Replace each listed value in .env with a unique random hexadecimal string.'
    } else {
        Pass 'No REPLACE_WITH placeholders remain in .env.'
    }
}

$required = @(
    'POSTGRES_DB', 'POSTGRES_BOOTSTRAP_USER', 'POSTGRES_BOOTSTRAP_PASSWORD',
    'APP_DB_USER', 'APP_DB_PASSWORD', 'REDIS_PASSWORD', 'RABBITMQ_USER',
    'RABBITMQ_PASSWORD', 'MINIO_ROOT_USER', 'MINIO_ROOT_PASSWORD',
    'JWT_SECRET', 'REALTIME_JWT_SECRET'
)
$missing = @($required | Where-Object { -not $envValues.ContainsKey($_) -or [string]::IsNullOrWhiteSpace($envValues[$_]) })
if ($missing.Count -gt 0) {
    Fail "Required variables are empty or missing: $($missing -join ', ')." 'Set every listed variable in .env using the names in .env.example.'
} else {
    Pass 'All required .env variables are present.'
}

foreach ($name in @('POSTGRES_BOOTSTRAP_PASSWORD', 'APP_DB_PASSWORD', 'REDIS_PASSWORD', 'RABBITMQ_PASSWORD', 'MINIO_ROOT_PASSWORD', 'JWT_SECRET', 'REALTIME_JWT_SECRET')) {
    if ($envValues.ContainsKey($name) -and $envValues[$name] -notmatch '^[A-Fa-f0-9]{64,}$') {
        Fail "$name must be hexadecimal so Compose connection URLs parse safely." 'Generate it with: [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))'
    }
}

foreach ($port in @(8000, 5432, 6379, 5672)) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
        Fail "Port $port is already in use (PID: $owners)." "Stop the process using port $port or edit the host-port binding in docker-compose.yml."
    } else {
        Pass "Port $port is free."
    }
}

if ($script:Failures -gt 0) {
    Write-Host "Doctor found $($script:Failures) issue(s). Fix them and rerun scripts/doctor.ps1." -ForegroundColor Red
    exit 1
}
Write-Host 'Doctor checks passed.' -ForegroundColor Green
exit 0
