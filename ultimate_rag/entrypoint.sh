#!/bin/bash
set -e

echo "=== Ultimate RAG API Server Startup ==="

# Download trees from S3 if configured
if [ -n "$TREES_S3_BUCKET" ]; then
    echo "Downloading trees from S3 bucket: $TREES_S3_BUCKET"

    S3_PREFIX="${TREES_S3_PREFIX:-trees/}"
    TARGET_DIR="${RAPTOR_TREES_DIR:-/app/trees}"

    echo "S3 prefix: $S3_PREFIX"
    echo "Target directory: $TARGET_DIR"

    # Sync trees from S3
    aws s3 sync "s3://${TREES_S3_BUCKET}/${S3_PREFIX}" "$TARGET_DIR" \
        --only-show-errors \
        --no-progress

    echo "Tree files downloaded:"
    ls -lh "$TARGET_DIR"

    # Check for the default tree
    DEFAULT_TREE="${RAPTOR_DEFAULT_TREE:-mega_ultra_v2}"
    if [ -f "$TARGET_DIR/${DEFAULT_TREE}.pkl" ] || [ -d "$TARGET_DIR/${DEFAULT_TREE}" ]; then
        echo "✓ Default tree '$DEFAULT_TREE' found"
    else
        echo "⚠ Warning: Default tree '$DEFAULT_TREE' not found in $TARGET_DIR"
        echo "Available trees:"
        ls "$TARGET_DIR"
    fi
else
    echo "No S3 bucket configured (TREES_S3_BUCKET not set)"
    echo "Using local trees from ${RAPTOR_TREES_DIR:-/app/trees}"
fi

echo "=== Starting API Server ==="
exec "$@"
