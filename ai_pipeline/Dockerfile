FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd -m -u 1000 appuser

# Install system dependencies
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy source code
COPY src /app/src

ENV PYTHONPATH=/app/src

RUN chown -R appuser:appuser /app
USER appuser

# Default command runs the scheduled tasks
# Override with specific subcommands: run-ingestion, run-teaching, run-maintenance
ENTRYPOINT ["python", "-m", "ai_learning_pipeline"]
CMD ["--help"]
