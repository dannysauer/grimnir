FROM python:3.12-slim

WORKDIR /app

# asyncpg needs a C compiler to build its extension
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY freki/pyproject.toml .
COPY freki/src/ src/
RUN pip install --no-cache-dir -e .

# Copy hlidskjalf (frontend) to be served as static files
COPY hlidskjalf/ /app/frontend

RUN useradd -m -u 1000 appuser
USER appuser

EXPOSE 8000

CMD ["freki"]
