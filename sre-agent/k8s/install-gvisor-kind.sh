#!/bin/bash
# Install gVisor (runsc) runtime in Kind cluster
set -e

echo "🔒 Installing gVisor runtime in Kind cluster..."

CLUSTER_NAME="incidentfox"
NODE_NAME="${CLUSTER_NAME}-control-plane"

# Check if kind cluster exists
if ! kind get clusters | grep -q "$CLUSTER_NAME"; then
    echo "❌ Kind cluster '$CLUSTER_NAME' not found. Run 'make kind-setup' first."
    exit 1
fi

echo "📦 Installing runsc binary in Kind node..."
docker exec $NODE_NAME bash -c '
set -e

# Install dependencies
apt-get update -qq && apt-get install -y wget

# Download runsc (map arch: arm64 -> aarch64, amd64 -> x86_64)
ARCH=$(dpkg --print-architecture)
if [ "$ARCH" = "arm64" ]; then
    GVISOR_ARCH="aarch64"
elif [ "$ARCH" = "amd64" ]; then
    GVISOR_ARCH="x86_64"
else
    GVISOR_ARCH="$ARCH"
fi

echo "Downloading gVisor for ${GVISOR_ARCH}..."
wget -q https://storage.googleapis.com/gvisor/releases/release/latest/${GVISOR_ARCH}/runsc \
    -O /usr/local/bin/runsc
wget -q https://storage.googleapis.com/gvisor/releases/release/latest/${GVISOR_ARCH}/containerd-shim-runsc-v1 \
    -O /usr/local/bin/containerd-shim-runsc-v1

chmod +x /usr/local/bin/runsc /usr/local/bin/containerd-shim-runsc-v1
/usr/local/bin/runsc --version
'

echo "⚙️  Configuring containerd with gVisor runtime..."
docker exec $NODE_NAME bash -c '
# Backup existing config
cp /etc/containerd/config.toml /etc/containerd/config.toml.backup

# Add runsc runtime
cat >> /etc/containerd/config.toml << EOF

# gVisor runtime
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc]
  runtime_type = "io.containerd.runsc.v1"
EOF

# Restart containerd
systemctl restart containerd
sleep 3
'

echo "✅ gVisor runtime installed!"
echo ""
echo "Next: kubectl apply -f k8s/gvisor-runtimeclass.yaml"

