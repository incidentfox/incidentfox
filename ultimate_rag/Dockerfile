# Ultimate RAG API Server
# NOTE: Build context should be the project root (.), not ./ultimate_rag
# e.g., docker build -f ultimate_rag/Dockerfile .
FROM python:3.11-slim-bookworm

WORKDIR /app

RUN useradd -m -u 1000 appuser

# Install system dependencies including AWS CLI
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    unzip \
    && curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip" \
    && unzip awscliv2.zip \
    && ./aws/install \
    && rm -rf awscliv2.zip aws \
    && rm -rf /var/lib/apt/lists/* \
    # Remove vulnerable wheel metadata from AWS CLI bundle (CVE-2026-24049)
    && find /usr/local/aws-cli -name "wheel-0.45*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true

# Copy requirements and install Python dependencies
COPY ultimate_rag/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install security patches (must run AFTER all pip installs)
RUN pip install --no-cache-dir --upgrade \
    "urllib3>=2.6.3" \
    "pyasn1>=0.6.2" \
    "jaraco.context>=6.1.0" \
    "starlette>=0.49.1" \
    "aiohttp>=3.13.3"

# Patch setuptools' vendored packages to fix CVEs
RUN pip install --no-cache-dir --upgrade "wheel>=0.46.2" "jaraco.context>=6.1.0" && \
    SITE_PKGS=$(python -c "import site; print(site.getsitepackages()[0])") && \
    rm -rf $SITE_PKGS/setuptools/_vendor/wheel-*.dist-info && \
    cp -r $SITE_PKGS/wheel $SITE_PKGS/setuptools/_vendor/ && \
    cp -r $SITE_PKGS/wheel-*.dist-info $SITE_PKGS/setuptools/_vendor/ && \
    rm -rf $SITE_PKGS/setuptools/_vendor/jaraco.context-*.dist-info && \
    rm -rf $SITE_PKGS/setuptools/_vendor/jaraco/context.py 2>/dev/null || true && \
    cp -r $SITE_PKGS/jaraco $SITE_PKGS/setuptools/_vendor/ 2>/dev/null || true && \
    cp -r $SITE_PKGS/jaraco_context-*.dist-info $SITE_PKGS/setuptools/_vendor/ 2>/dev/null || true

# Copy the RAPTOR library to /app/raptor/ (required for pickle deserialization)
# The pickle files contain objects like raptor.tree_structures.Node which need
# the raptor module at the top level for Python to find during unpickling
COPY ultimate_rag/raptor_lib/ ./raptor/

# Copy Ultimate RAG package
COPY ultimate_rag/agents/ ./ultimate_rag/agents/
COPY ultimate_rag/api/ ./ultimate_rag/api/
COPY ultimate_rag/core/ ./ultimate_rag/core/
COPY ultimate_rag/graph/ ./ultimate_rag/graph/
COPY ultimate_rag/ingestion/ ./ultimate_rag/ingestion/
COPY ultimate_rag/intelligence/ ./ultimate_rag/intelligence/
COPY ultimate_rag/raptor/ ./ultimate_rag/raptor/
COPY ultimate_rag/raptor_lib/ ./ultimate_rag/raptor_lib/
COPY ultimate_rag/retrieval/ ./ultimate_rag/retrieval/
RUN echo "" > ./ultimate_rag/__init__.py

# Copy entrypoint script
COPY ultimate_rag/entrypoint.sh .
RUN chmod +x entrypoint.sh

# Create trees directory
RUN mkdir -p /app/trees

RUN chown -R appuser:appuser /app /app/trees
USER appuser

# Environment
ENV RAPTOR_TREES_DIR=/app/trees
ENV RAPTOR_DEFAULT_TREE=mega_ultra_v2
ENV PORT=8000
ENV PYTHONPATH=/app

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "-m", "ultimate_rag.api.server"]
