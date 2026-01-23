FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Node.js (required for MCP preview functionality)
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Upgrade wheel to fix CVE-2026-24049
RUN pip install --no-cache-dir --upgrade "wheel>=0.46.2"

COPY requirements.runtime.txt /app/requirements.runtime.txt
RUN pip install --no-cache-dir -r /app/requirements.runtime.txt \
    && pip install --no-cache-dir --upgrade \
    "urllib3>=2.6.3" \
    "pyasn1>=0.6.2" \
    "jaraco.context>=6.1.0" \
    "starlette>=0.49.1"

# Install uv package manager (required for Python MCP servers like AWS EKS MCP)
RUN pip install --no-cache-dir uv

COPY src /app/src
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
COPY scripts /app/scripts
COPY templates /app/templates

ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
