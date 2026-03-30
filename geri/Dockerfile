FROM python:3.12-slim

WORKDIR /app

# asyncpg needs a C compiler to build its extension
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY geri/pyproject.toml .
COPY geri/src/ src/
RUN pip install --no-cache-dir -e .

RUN useradd -m -u 1000 appuser
USER appuser

EXPOSE 5005/udp

CMD ["geri"]
