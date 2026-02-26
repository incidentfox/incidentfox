#!/bin/sh
# Git credential helper for IncidentFox sandbox environment.
#
# Fetches a GitHub token from the credential-resolver service using the
# sandbox JWT. This lets the agent use native git commands (clone, push, pull)
# with HTTPS URLs, authenticated transparently through the credential proxy.
#
# Git calls this script with "get" when it needs credentials.
# Protocol: https://git-scm.com/docs/gitcredentials#_custom_helpers

# Only handle "get" requests (not "store" or "erase")
case "$1" in
    get) ;;
    *) exit 0 ;;
esac

# Read input (host, protocol, etc.) — we only care about github.com hosts
HOST=""
while IFS='=' read -r key value; do
    case "$key" in
        host) HOST="$value" ;;
    esac
done

# Only provide credentials for GitHub hosts
case "$HOST" in
    github.com|*.github.com|*.githubusercontent.com) ;;
    *) exit 0 ;;
esac

# Credential-resolver URL (set by sandbox_manager.py)
CR_URL="${CREDENTIAL_RESOLVER_URL:-http://credential-resolver-svc:8002}"

# SANDBOX_JWT may be in env or written to file by /claim endpoint
JWT="${SANDBOX_JWT}"
if [ -z "$JWT" ] && [ -f /tmp/sandbox-jwt ]; then
    JWT=$(cat /tmp/sandbox-jwt)
fi
if [ -z "$JWT" ]; then
    exit 1
fi

# Fetch token from credential-resolver
RESPONSE=$(curl -sf -H "X-Sandbox-JWT: ${JWT}" "${CR_URL}/api/git-token" 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$RESPONSE" ]; then
    exit 1
fi

# Extract token from JSON response {"token": "..."}
TOKEN=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])" 2>/dev/null)
if [ -z "$TOKEN" ]; then
    exit 1
fi

# Output in git credential format
printf 'protocol=https\nhost=%s\nusername=x-access-token\npassword=%s\n' "$HOST" "$TOKEN"
