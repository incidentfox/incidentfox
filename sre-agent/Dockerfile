# IncidentFox AI SRE Agent - Sandbox Image
# Runs inside Kubernetes agent-sandbox for isolated investigations
# Exposes FastAPI server on port 8888 for SandboxClient interaction

FROM python:3.11-slim

# Detect architecture and set variables for kubectl and AWS CLI
ARG TARGETARCH
RUN echo "Building for architecture: ${TARGETARCH}"

# ==============================================================================
# PREINSTALLED INTEGRATIONS
# ==============================================================================
# We preinstall all integration CLIs (~200MB) for these reasons:
# 1. Multi-tenant: Same image serves all customers with different configs
# 2. Performance: No runtime installation delays (30+ seconds per tool)
# 3. Simplicity: No build matrix or runtime discovery needed
# 4. Security: Avoid runtime package installation from sandboxed environment
#
# Preinstalled integrations:
# - kubectl (~50MB): Kubernetes cluster management
# - aws CLI (~150MB): AWS resource inspection & management
# - Node.js + claude-code: Claude Code CLI for agent framework
#
# Tools only execute if credentials are configured, no security risk from presence.
# ==============================================================================

# Install Node.js (required by Claude Code CLI), kubectl, AWS CLI, and utilities
RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    jq \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    # Install kubectl for correct architecture
    && KUBECTL_ARCH=$([ "${TARGETARCH}" = "arm64" ] && echo "arm64" || echo "amd64") \
    && curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/${KUBECTL_ARCH}/kubectl" \
    && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl \
    && rm kubectl \
    # Install AWS CLI for correct architecture
    && AWS_ARCH=$([ "${TARGETARCH}" = "arm64" ] && echo "aarch64" || echo "x86_64") \
    && curl "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_ARCH}.zip" -o "awscliv2.zip" \
    && unzip awscliv2.zip \
    && ./aws/install \
    && rm -rf aws awscliv2.zip \
    && rm -rf /var/lib/apt/lists/* \
    # Verify installations
    && kubectl version --client \
    && aws --version

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Install uv for faster, deterministic Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create app directory
WORKDIR /app

# Copy application files
COPY agent.py .
COPY sandbox_server.py .
COPY server.py .
COPY sandbox_manager.py .
COPY events.py .
COPY pyproject.toml .
COPY uv.lock .
COPY .claude/ ./.claude/
COPY kubeconfig-demo.yaml /app/kubeconfig-demo.yaml

# Install Python dependencies using uv with lock file for deterministic builds
# --system: Install to system Python (not venv, we're in a container)
# --no-cache: Don't cache downloads (keeps image size down)
RUN uv pip install --system --no-cache .

# Create non-root user and workspace directory
RUN useradd -m -u 1000 agent && \
    mkdir -p /workspace /home/agent/.kube /home/agent/.aws && \
    cp /app/kubeconfig-demo.yaml /home/agent/.kube/config && \
    chown -R agent:agent /app /workspace /home/agent/.kube /home/agent/.aws

USER agent

# Set working directory to workspace (where persistent volume will be mounted)
WORKDIR /workspace

# Expose sandbox server port (agent-sandbox standard)
EXPOSE 8888

# Run FastAPI sandbox server
CMD ["python", "/app/sandbox_server.py"]
