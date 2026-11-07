.PHONY: check test lint type security audit migrate lock install-dev
check: lint type security audit test
test:
	pytest --cov=app --cov-report=term-missing --cov-fail-under=80
lint:
	ruff check app tests migrations
type:
	mypy app
security:
	bandit -c pyproject.toml -r app
audit:
	pip-audit
migrate:
	alembic upgrade head
lock:
	pip-compile --resolver=backtracking --generate-hashes --extra dev --output-file requirements.lock pyproject.toml
install-dev: lock
	python -m pip install --require-hashes -r requirements.lock
