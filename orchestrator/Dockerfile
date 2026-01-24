FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
  gcc \
  && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir --upgrade \
    "urllib3>=2.6.3" \
    "pyasn1>=0.6.2" \
    "jaraco.context>=6.1.0" \
    "starlette>=0.49.1" \
    "aiohttp>=3.9.0"

# Patch setuptools' vendored wheel to fix CVE-2026-24049 (must run AFTER all pip installs)
# setuptools bundles an old wheel in _vendor/ that Trivy flags as vulnerable
RUN pip install --no-cache-dir --upgrade "wheel>=0.46.2" && \
    SITE_PKGS=$(python -c "import site; print(site.getsitepackages()[0])") && \
    rm -rf $SITE_PKGS/setuptools/_vendor/wheel-*.dist-info && \
    cp -r $SITE_PKGS/wheel $SITE_PKGS/setuptools/_vendor/ && \
    cp -r $SITE_PKGS/wheel-*.dist-info $SITE_PKGS/setuptools/_vendor/

ENV PYTHONPATH=/app/src

EXPOSE 8070

CMD ["python3", "-m", "uvicorn", "incidentfox_orchestrator.api_server:app", "--host", "0.0.0.0", "--port", "8070"]


