FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install mimir (shared models/migrations package) first
COPY mimir/ /mimir
RUN pip install --no-cache-dir /mimir

COPY freki/pyproject.toml .
COPY freki/src/ src/
RUN pip install --no-cache-dir -e .

# Copy frontend to be served as static files
COPY hlidskjalf/ /app/frontend

RUN useradd -m -u 1000 appuser
USER appuser

EXPOSE 8000

CMD ["freki"]
