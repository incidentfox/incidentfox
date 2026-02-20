"""
Minimal webhook receiver for Vercel Log Drain testing.

Handles:
1. Vercel URL verification (GET with x-vercel-verify)
2. Log Drain payloads (POST with JSON/NDJSON body)
3. Signature verification via HMAC-SHA1
"""

import hashlib
import hmac
import json
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

WEBHOOK_SECRET = os.environ.get(
    "VERCEL_WEBHOOK_SECRET",
    "ba6d928774201fd421cffdf6fde12c6ac3a9dba0e98da868281d9f30c77bd87c",
)
# Vercel provides this value when creating the log drain — echo it in all responses
VERCEL_VERIFY = os.environ.get(
    "VERCEL_VERIFY", "5af173b41964a3df9b543a38e043da998ff1a83d"
)
PORT = int(os.environ.get("PORT", "9876"))


class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Handle Vercel URL verification."""
        verify = self.headers.get("x-vercel-verify") or VERCEL_VERIFY
        print(f"\n[{datetime.now()}] GET {self.path} (verify={verify})")
        self.send_response(200)
        self.send_header("x-vercel-verify", verify)
        self.end_headers()
        self.wfile.write(verify.encode())

    def do_POST(self):
        """Handle incoming log drain events."""
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length).decode("utf-8")

        # Verify signature
        signature = self.headers.get("x-vercel-signature", "")
        expected = hmac.new(
            WEBHOOK_SECRET.encode("utf-8"),
            raw_body.encode("utf-8"),
            hashlib.sha1,
        ).hexdigest()

        sig_valid = hmac.compare_digest(expected, signature)

        print(f"\n{'='*60}")
        print(f"[{datetime.now()}] POST {self.path}")
        print(f"  Signature: {'VALID' if sig_valid else 'INVALID'}")
        print(f"  x-vercel-signature: {signature[:20]}...")
        print(f"  Body length: {len(raw_body)} bytes")

        # Parse payload
        try:
            logs = json.loads(raw_body)
            if not isinstance(logs, list):
                logs = [logs]
        except json.JSONDecodeError:
            # Try NDJSON
            logs = []
            for line in raw_body.strip().split("\n"):
                if line.strip():
                    try:
                        logs.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        # Display log entries
        error_count = 0
        for log in logs:
            level = log.get("level", log.get("type", "unknown"))
            message = log.get("message", "")[:200]
            path = log.get("path", log.get("proxy", {}).get("path", ""))
            status = log.get("statusCode", log.get("proxy", {}).get("statusCode", ""))
            deployment_id = log.get("deploymentId", "")

            if level in ("error", "warning"):
                error_count += 1
                print(f"\n  [{level.upper()}] {message}")
                print(f"    path={path} status={status}")
                print(f"    deploymentId={deployment_id}")

        print(f"\n  Total logs: {len(logs)}, Errors/Warnings: {error_count}")
        print(f"{'='*60}")

        # Save to file for inspection
        with open("received_logs.jsonl", "a") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        self.send_response(200)
        self.send_header("x-vercel-verify", VERCEL_VERIFY)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # Suppress default logging


if __name__ == "__main__":
    print(f"Starting Vercel Log Drain receiver on port {PORT}")
    print(f"Webhook secret: {WEBHOOK_SECRET[:16]}...")
    print("Waiting for events...\n")
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        server.server_close()
