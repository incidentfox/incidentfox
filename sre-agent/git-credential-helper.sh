#!/bin/sh
# Git credential helper for IncidentFox sandbox environment.
#
# Returns the sandbox JWT as a Basic auth password. The credential-resolver's
# /git/ proxy validates the JWT and injects real GitHub credentials when
# forwarding to github.com. This way, actual GitHub tokens never reach the
# sandbox — only the JWT (which the sandbox already possesses) is used.
#
# Git calls this script with "get" when it needs credentials.
# Protocol: https://git-scm.com/docs/gitcredentials#_custom_helpers

# Only handle "get" requests (not "store" or "erase")
case "$1" in
    get) ;;
    *) exit 0 ;;
esac

# Read and discard stdin (git sends host/protocol info, we don't need it
# since URL rewriting already routes to credential-resolver)
while IFS='=' read -r key value; do
    :
done

# SANDBOX_JWT may be in env or written to file by /claim endpoint
JWT="${SANDBOX_JWT}"
if [ -z "$JWT" ] && [ -f /tmp/sandbox-jwt ]; then
    JWT=$(cat /tmp/sandbox-jwt)
fi
if [ -z "$JWT" ]; then
    exit 1
fi

# Return JWT as password — credential-resolver validates it and injects
# real GitHub credentials when proxying to github.com
printf 'username=x-access-token\npassword=%s\n' "$JWT"
