FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install mimir (shared models package) first
COPY mimir/ /mimir
RUN pip install --no-cache-dir /mimir

COPY nornir/pyproject.toml .
COPY nornir/src/ src/
RUN pip install --no-cache-dir -e .

RUN useradd -m -u 1000 appuser
USER appuser

CMD ["nornir"]
