FROM python:3.12-slim

WORKDIR /app

# Build deps for psycopg / cryptography wheels are usually prebuilt; keep slim.
COPY pyproject.toml ./
COPY arescope ./arescope
RUN pip install --no-cache-dir .

# Connectors that shell out (maigret) need the CLI on PATH — installed via deps.
ENV PYTHONUNBUFFERED=1
