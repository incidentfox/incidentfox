FROM python:3.11-slim-bookworm as base

WORKDIR /app

# Install system dependencies and Node.js (for MCP servers like npx-based tools)
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && node --version && npm --version

# Install Poetry
RUN pip install --no-cache-dir poetry==1.7.1

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Configure Poetry and install dependencies (tracing, CI tools, database, observability, issue tracking)
# Also install AWS CLI for EKS authentication (aws eks get-token)
RUN poetry config virtualenvs.create false \
    && poetry install --no-root --only main --extras "langfuse github slack snowflake postgresql bigquery splunk jira gitlab notion" \
    && pip install --no-cache-dir --upgrade "jaraco.context>=6.1.0" "starlette>=0.49.1" \
    && pip install --no-cache-dir awscli

# Patch setuptools' vendored wheel to fix CVE-2026-24049 (must run AFTER all pip/poetry installs)
# setuptools bundles an old wheel in _vendor/ that Trivy flags as vulnerable
RUN pip install --no-cache-dir --upgrade "wheel>=0.46.2" && \
    SITE_PKGS=$(python -c "import site; print(site.getsitepackages()[0])") && \
    rm -rf $SITE_PKGS/setuptools/_vendor/wheel-*.dist-info && \
    cp -r $SITE_PKGS/wheel $SITE_PKGS/setuptools/_vendor/ && \
    cp -r $SITE_PKGS/wheel-*.dist-info $SITE_PKGS/setuptools/_vendor/

# Copy application code
COPY src/ ./src/

# Set Python path
ENV PYTHONPATH=/app/src

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default command - run in API mode
CMD ["python", "-m", "ai_agent", "--mode", "api"]

# ==========================================
# Development Stage
# ==========================================
FROM base as development

USER root

# Install dev dependencies
RUN poetry install --no-root

# Install dev tools
RUN pip install --no-cache-dir ipython

USER appuser

# ==========================================
# Test Stage
# ==========================================
FROM development as test

USER root

# Copy tests
COPY tests/ ./tests/

USER appuser

CMD ["pytest", "-v"]

# ==========================================
# Runtime Stage (final)
# ==========================================
# IMPORTANT: Docker builds the *last* stage by default. Keep runtime last so
# `docker build -t ... ./agent` produces an API image (not the test image).
FROM base as runtime
