#!/bin/sh
# Credential-resolver entrypoint: HTTP on 8002.
# TLS termination for gh CLI (port 8443) is handled by the Envoy sidecar
# in the sandbox pod, not here.
exec uvicorn credential_resolver.main:app --host 0.0.0.0 --port 8002
