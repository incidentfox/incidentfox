# RAPTOR Knowledge Base API Server
FROM python:3.11-slim-bookworm

WORKDIR /app

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
    # AWS CLI bundles its own Python with wheel-0.45.1 which Trivy flags as vulnerable
    && find /usr/local/aws-cli -name "wheel-0.45*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install API server dependencies and security patches
RUN pip install --no-cache-dir fastapi uvicorn httpx \
    && pip install --no-cache-dir --upgrade \
    "urllib3>=2.6.3" \
    "pyasn1>=0.6.2" \
    "jaraco.context>=6.1.0" \
    "starlette>=0.49.1" \
    "aiohttp>=3.13.3"

# Patch setuptools' vendored packages to fix CVEs (must run AFTER all pip installs)
# setuptools bundles old versions in _vendor/ that Trivy flags as vulnerable:
# - wheel-0.45.1 (CVE-2026-24049)
# - jaraco.context-5.3.0 (CVE-2026-23949)
RUN pip install --no-cache-dir --upgrade "wheel>=0.46.2" "jaraco.context>=6.1.0" && \
    SITE_PKGS=$(python -c "import site; print(site.getsitepackages()[0])") && \
    # Patch wheel
    rm -rf $SITE_PKGS/setuptools/_vendor/wheel-*.dist-info && \
    cp -r $SITE_PKGS/wheel $SITE_PKGS/setuptools/_vendor/ && \
    cp -r $SITE_PKGS/wheel-*.dist-info $SITE_PKGS/setuptools/_vendor/ && \
    # Patch jaraco.context
    rm -rf $SITE_PKGS/setuptools/_vendor/jaraco.context-*.dist-info && \
    rm -rf $SITE_PKGS/setuptools/_vendor/jaraco/context.py 2>/dev/null || true && \
    cp -r $SITE_PKGS/jaraco $SITE_PKGS/setuptools/_vendor/ 2>/dev/null || true && \
    cp -r $SITE_PKGS/jaraco_context-*.dist-info $SITE_PKGS/setuptools/_vendor/ 2>/dev/null || true

# Copy RAPTOR library and API server
COPY raptor/ ./raptor/
COPY api_server.py .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Create trees directory
RUN mkdir -p /app/trees

# Environment
ENV RAPTOR_TREES_DIR=/app/trees
ENV RAPTOR_DEFAULT_TREE=mega_ultra_v2
ENV PORT=8000

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "api_server.py"]
