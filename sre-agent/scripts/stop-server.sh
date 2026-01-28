#!/bin/bash
# Stop the local development server

set -e

echo "🛑 Stopping server..."

if pgrep -f "python.*server.py" > /dev/null; then
    PID=$(pgrep -f "python.*server.py")
    echo "  Found server process (PID: $PID)"
    kill $PID
    sleep 1
    
    # Force kill if still running
    if pgrep -f "python.*server.py" > /dev/null; then
        echo "  Force killing..."
        pkill -9 -f "python.*server.py"
    fi
    
    echo "✅ Server stopped"
else
    echo "  ℹ️  Server not running"
fi

