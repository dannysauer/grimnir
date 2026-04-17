FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install mimir (shared models package) first
COPY mimir/ /mimir
RUN pip install --no-cache-dir /mimir

COPY volva/pyproject.toml .
COPY volva/src/ src/
RUN pip install --no-cache-dir -e .

RUN useradd -m -u 1000 appuser
USER appuser

EXPOSE 8002

CMD ["volva"]
