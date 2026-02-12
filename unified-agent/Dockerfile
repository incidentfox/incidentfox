# ==============================================================================
# IncidentFox Unified Agent - Sandbox Image
# ==============================================================================
# Runs inside Kubernetes agent-sandbox for isolated investigations.
# Exposes FastAPI server on port 8888 for SandboxClient interaction.
#
# This unified image consolidates agent/ and sre-agent/ into a single runtime.
# ==============================================================================

FROM python:3.11-slim as base

# Detect architecture for multi-arch builds
ARG TARGETARCH
RUN echo "Building for architecture: ${TARGETARCH}"

# ==============================================================================
# PREINSTALLED INTEGRATIONS
# ==============================================================================
# We preinstall all integration CLIs for:
# 1. Multi-tenant: Same image serves all customers with different configs
# 2. Performance: No runtime installation delays
# 3. Security: Avoid runtime package installation from sandboxed environment
#
# Included:
# - kubectl (~50MB): Kubernetes cluster management
# - aws CLI (~150MB): AWS resource inspection & management
# - Node.js: Required for MCP servers and Claude Code CLI
# ==============================================================================

# Pin kubectl version for reproducible builds
ARG KUBECTL_VERSION=v1.31.0

# Install Node.js, kubectl, AWS CLI, and utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    unzip \
    jq \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    # Install kubectl for correct architecture
    && KUBECTL_ARCH=$([ "${TARGETARCH}" = "arm64" ] && echo "arm64" || echo "amd64") \
    && curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${KUBECTL_ARCH}/kubectl" \
    && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl \
    && rm kubectl \
    # Install AWS CLI for correct architecture
    && AWS_ARCH=$([ "${TARGETARCH}" = "arm64" ] && echo "aarch64" || echo "x86_64") \
    && curl "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_ARCH}.zip" -o "awscliv2.zip" \
    && unzip -q awscliv2.zip \
    && ./aws/install \
    && rm -rf aws awscliv2.zip \
    && rm -rf /var/lib/apt/lists/* \
    # Verify installations
    && kubectl version --client \
    && aws --version \
    && node --version

# Install Claude Code CLI (for MCP integration)
RUN npm install -g @anthropic-ai/claude-code

# Install uv for fast, deterministic Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# ==============================================================================
# Python Dependencies
# ==============================================================================

# Copy dependency files first for better caching
COPY pyproject.toml ./

# Install Python dependencies using uv
# --system: Install to system Python (not venv, we're in a container)
# --no-cache: Don't cache downloads (keeps image size down)
RUN uv pip install --system --no-cache .

# Install optional dependencies for full functionality
RUN uv pip install --system --no-cache \
    "PyGithub>=2.1.0" \
    "slack-sdk>=3.27.0" \
    "datadog-api-client>=2.20.0" \
    "elasticsearch>=8.0.0" \
    "requests>=2.32.0" \
    || true

# ==============================================================================
# Application Code
# ==============================================================================

# Copy application source
COPY src/ ./src/

# Set Python path
ENV PYTHONPATH=/app/src

# ==============================================================================
# Runtime Setup
# ==============================================================================

# Create non-root user and workspace directory
RUN useradd -m -u 1000 agent && \
    mkdir -p /workspace /home/agent/.kube /home/agent/.aws && \
    chown -R agent:agent /app /workspace /home/agent

USER agent

# Working directory for investigations
WORKDIR /workspace

# Expose sandbox server port
EXPOSE 8888

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -sf http://localhost:8888/health || exit 1

# Run FastAPI sandbox server
CMD ["python", "-m", "unified_agent.sandbox.server"]


# ==============================================================================
# Development Stage
# ==============================================================================
FROM base as development

USER root

# Install dev tools
RUN uv pip install --system --no-cache \
    pytest \
    pytest-asyncio \
    pytest-cov \
    ruff \
    ipython

USER agent

# Override to run shell for dev
CMD ["/bin/bash"]


# ==============================================================================
# Test Stage
# ==============================================================================
FROM development as test

USER root

# Copy tests
COPY tests/ ./tests/

USER agent

CMD ["pytest", "-v", "--tb=short"]


# ==============================================================================
# Runtime Stage (final - this is what gets built by default)
# ==============================================================================
FROM base as runtime
