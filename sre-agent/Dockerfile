# Copyright 2026 IncidentFox, Inc.
#
# Licensed under the Business Source License 1.1 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://github.com/incidentfox/incidentfox/blob/main/LICENSE-ENTERPRISE
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
# - gh (~30MB): GitHub CLI for repository operations
# - Node.js + claude-code: Claude Code CLI for agent framework
#
# Tools only execute if credentials are configured, no security risk from presence.
# ==============================================================================

# Install Node.js (required by Claude Code CLI), kubectl, AWS CLI, gh CLI, and utilities
# Pin versions for reproducible builds
ARG KUBECTL_VERSION=v1.31.0
ARG GH_VERSION=2.65.0
RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    jq \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    # Install kubectl for correct architecture (pinned version)
    && KUBECTL_ARCH=$([ "${TARGETARCH}" = "arm64" ] && echo "arm64" || echo "amd64") \
    && curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${KUBECTL_ARCH}/kubectl" \
    && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl \
    && rm kubectl \
    # Install AWS CLI for correct architecture
    && AWS_ARCH=$([ "${TARGETARCH}" = "arm64" ] && echo "aarch64" || echo "x86_64") \
    && curl "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_ARCH}.zip" -o "awscliv2.zip" \
    && unzip awscliv2.zip \
    && ./aws/install \
    && rm -rf aws awscliv2.zip \
    # Install GitHub CLI for correct architecture (pinned version)
    && GH_ARCH=$([ "${TARGETARCH}" = "arm64" ] && echo "arm64" || echo "amd64") \
    && curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${GH_ARCH}.tar.gz" \
       | tar xz \
    && install -o root -g root -m 0755 "gh_${GH_VERSION}_linux_${GH_ARCH}/bin/gh" /usr/local/bin/gh \
    && rm -rf "gh_${GH_VERSION}_linux_${GH_ARCH}" \
    && rm -rf /var/lib/apt/lists/* \
    # Verify installations
    && kubectl version --client \
    && aws --version \
    && gh --version

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
COPY auth.py .
COPY config.py .
COPY pyproject.toml .
COPY uv.lock .
COPY .claude/ ./.claude/
COPY kubeconfig-demo.yaml /app/kubeconfig-demo.yaml
COPY git-credential-helper.sh /usr/local/bin/git-credential-incidentfox

# Install Python dependencies using uv with lock file for deterministic builds
# --system: Install to system Python (not venv, we're in a container)
# --no-cache: Don't cache downloads (keeps image size down)
RUN uv pip install --system --no-cache .

# Trust credential-resolver's self-signed TLS cert so gh CLI can connect via HTTPS.
# The cert is shared between credential-resolver (serves HTTPS) and sandbox (trusts it).
COPY credential-proxy/certs/credential-resolver.crt /usr/local/share/ca-certificates/credential-resolver.crt
RUN update-ca-certificates

# Create non-root user and workspace directory
RUN useradd -m -u 1000 agent && \
    mkdir -p /workspace /home/agent/.kube /home/agent/.aws && \
    cp /app/kubeconfig-demo.yaml /home/agent/.kube/config && \
    # Configure git credential helper — sends sandbox JWT as Basic auth password
    # to credential-resolver's /git/ proxy (URL rewriting set via GIT_CONFIG_* env vars)
    git config --system credential.helper incidentfox && \
    chown -R agent:agent /app /workspace /home/agent/.kube /home/agent/.aws

USER agent

# Set working directory to workspace (where persistent volume will be mounted)
WORKDIR /workspace

# Expose sandbox server port (agent-sandbox standard)
EXPOSE 8888

# Run FastAPI sandbox server
CMD ["python", "/app/sandbox_server.py"]
