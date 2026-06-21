FROM python:3.12-slim

WORKDIR /app

# Build deps for psycopg / cryptography wheels are usually prebuilt; keep slim.
COPY pyproject.toml ./
COPY arescope ./arescope
# Include the [connectors] extra so Holehe + Maigret (and their dep trees, incl.
# trio) ship in the deployed worker — without it they degrade to coverage gaps
# and those tools never actually run.
RUN pip install --no-cache-dir ".[connectors]"

ENV PYTHONUNBUFFERED=1
