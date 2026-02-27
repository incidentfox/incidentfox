#!/bin/sh
# Dual-port entrypoint: HTTP on 8002 (always) + HTTPS on 8443 (if certs exist).
# Uses uvicorn CLI directly to avoid dual-import issue (see Dockerfile comment).
trap 'kill 0' TERM INT

uvicorn credential_resolver.main:app --host 0.0.0.0 --port 8002 &
HTTP_PID=$!

if [ -f /app/certs/credential-resolver.crt ] && [ -f /app/certs/credential-resolver.key ]; then
    uvicorn credential_resolver.main:app --host 0.0.0.0 --port 8443 \
        --ssl-keyfile /app/certs/credential-resolver.key \
        --ssl-certfile /app/certs/credential-resolver.crt &
fi

# Wait only for the HTTP process (the critical one).
# If the HTTPS process crashes, the container stays alive for the
# liveness probe on port 8002.
wait $HTTP_PID
