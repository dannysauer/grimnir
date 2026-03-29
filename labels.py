FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install models package first (shared dependency)
COPY ../models /models
RUN pip install --no-cache-dir /models

COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir -e .

# Copy frontend to be served as static files
COPY ../frontend /app/frontend

RUN useradd -m -u 1000 appuser
USER appuser

EXPOSE 8000

CMD ["csi-backend"]
