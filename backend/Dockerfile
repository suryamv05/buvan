FROM python:3.13.18-slim-bookworm AS dependencies
WORKDIR /build
COPY pyproject.toml ./
RUN pip install --no-cache-dir pip-tools==7.6.2 \
    && pip-compile --resolver=backtracking --generate-hashes --output-file=/tmp/requirements.lock pyproject.toml \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && /opt/venv/bin/pip check

FROM python:3.13.18-slim-bookworm
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home-dir /app app
COPY --from=dependencies /opt/venv /opt/venv
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
RUN python -c "import uvicorn, fastapi, sqlalchemy, alembic, celery, redis, boto3" && pip check
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
