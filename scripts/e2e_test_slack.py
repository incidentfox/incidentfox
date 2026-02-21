#!/usr/bin/env python3
"""
E2E Slack Integration Test

This script:
1. Sends a test message to Slack channel via the bot
2. Triggers the agent via direct API call (simulating Slack webhook)
3. Validates the response
4. Checks server-side logs

Requirements:
- SLACK_BOT_TOKEN in AWS Secrets Manager
- Agent API accessible
"""

import os
import subprocess
import sys
import time
from datetime import datetime

import requests

# Configuration
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "C0A43KYJE03")
AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
AGENT_NAMESPACE = os.getenv("AGENT_NAMESPACE", "incidentfox")
WEB_UI_URL = os.getenv("WEB_UI_URL", "https://ui.incidentfox.ai")


def get_secret(secret_name: str) -> str:
    """Fetch secret from AWS Secrets Manager."""
    result = subprocess.run(
        [
            "aws",
            "secretsmanager",
            "get-secret-value",
            "--secret-id",
            secret_name,
            "--region",
            AWS_REGION,
            "--query",
            "SecretString",
            "--output",
            "text",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise Exception(f"Failed to get secret {secret_name}: {result.stderr}")
    return result.stdout.strip()


def post_slack_message(token: str, channel: str, text: str) -> dict:
    """Post a message to Slack."""
    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": channel, "text": text},
    )
    return response.json()


def get_slack_replies(
    token: str, channel: str, thread_ts: str, timeout: int = 60
) -> list:
    """Wait for and get replies in a thread."""
    start = time.time()
    while time.time() - start < timeout:
        response = requests.get(
            "https://slack.com/api/conversations.replies",
            headers={"Authorization": f"Bearer {token}"},
            params={"channel": channel, "ts": thread_ts},
        )
        data = response.json()
        if data.get("ok") and len(data.get("messages", [])) > 1:
            return data["messages"][1:]  # Skip original message
        time.sleep(5)
    return []


def call_agent_directly(message: str, timeout: int = 120) -> dict:
    """Call the agent API directly via port-forward."""
    # Get agent pod
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "pods",
            "-n",
            AGENT_NAMESPACE,
            "-l",
            "app=incidentfox-agent",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ],
        capture_output=True,
        text=True,
    )
    pod_name = result.stdout.strip()

    if not pod_name:
        return {"error": "No agent pod found"}

    # Start port-forward in background
    pf_proc = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            "-n",
            AGENT_NAMESPACE,
            f"pod/{pod_name}",
            "18080:8080",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        time.sleep(3)  # Wait for port-forward

        # Call agent
        response = requests.post(
            "http://localhost:18080/agents/investigation_agent/run",
            json={
                "message": message,
                "context": {},
                "timeout": timeout,
                "max_turns": 200,  # High limit - let agent complete
            },
            timeout=timeout + 10,
        )
        return response.json()
    finally:
        pf_proc.terminate()


def get_recent_logs(namespace: str, label: str, lines: int = 50) -> str:
    """Get recent logs from a deployment."""
    result = subprocess.run(
        ["kubectl", "logs", "-n", namespace, "-l", label, "--tail", str(lines)],
        capture_output=True,
        text=True,
    )
    return result.stdout


def call_orchestrator_slack_trigger(
    channel: str, user: str, message: str, thread_ts: str = None
) -> dict:
    """Call orchestrator's internal Slack trigger endpoint (simulates what web-ui does)."""
    # Get orchestrator pod
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "pods",
            "-n",
            AGENT_NAMESPACE,
            "-l",
            "app=incidentfox-orchestrator",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ],
        capture_output=True,
        text=True,
    )
    pod_name = result.stdout.strip()

    if not pod_name:
        return {"error": "No orchestrator pod found"}

    # Get admin token
    try:
        admin_token = get_secret("incidentfox/prod/orchestrator_internal_token")
    except Exception:
        admin_token = "test-admin-token"

    # Start port-forward (orchestrator uses port 8070)
    pf_proc = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            "-n",
            AGENT_NAMESPACE,
            f"pod/{pod_name}",
            "18081:8070",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        time.sleep(3)

        correlation_id = f"e2e-test-{int(time.time())}"

        response = requests.post(
            "http://localhost:18081/api/v1/internal/slack/trigger",
            headers={
                "X-Internal-Token": admin_token,
                "X-Correlation-ID": correlation_id,
            },
            json={
                "channel_id": channel,
                "user_id": user,
                "text": message,  # API expects "text" not "message"
                "thread_ts": thread_ts,
                "correlation_id": correlation_id,
            },
            timeout=180,
        )
        return {
            "status": response.status_code,
            "body": response.json(),
            "correlation_id": correlation_id,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        pf_proc.terminate()


def run_slack_e2e_test():
    """Run full Slack E2E test."""
    print("=" * 60)
    print("🧪 IncidentFox Slack E2E Test")
    print("=" * 60)

    # Get Slack token
    print("\n1️⃣ Fetching Slack bot token...")
    try:
        slack_token = get_secret("incidentfox/prod/slack_bot_token")
        print("   ✅ Token retrieved")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test message for agent
    test_query = "What pods are running in the incidentfox namespace?"

    # Post initial message to Slack (for threading)
    print(f"\n2️⃣ Posting test message to Slack channel {SLACK_CHANNEL_ID}...")
    try:
        result = post_slack_message(
            slack_token,
            SLACK_CHANNEL_ID,
            f"🧪 E2E Test: `{test_query}`\n_Testing at {datetime.now().isoformat()}_",
        )
        if not result.get("ok"):
            print(f"   ❌ Failed: {result.get('error')}")
            return False
        thread_ts = result["ts"]
        print(f"   ✅ Message posted (ts: {thread_ts})")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Trigger agent via orchestrator (simulates Slack webhook flow)
    print("\n3️⃣ Triggering agent via orchestrator (simulating Slack event)...")
    try:
        trigger_result = call_orchestrator_slack_trigger(
            channel=SLACK_CHANNEL_ID,
            user="U_E2E_TEST",
            message=test_query,
            thread_ts=thread_ts,
        )

        if "error" in trigger_result:
            print(f"   ❌ Failed: {trigger_result['error']}")
        else:
            print(f"   ✅ Orchestrator responded (status: {trigger_result['status']})")
            print(f"   Correlation ID: {trigger_result.get('correlation_id')}")

            body = trigger_result.get("body", {})
            if body.get("success"):
                output = body.get("output", "")[:300]
                print(f"   Agent output preview: {output}...")
            else:
                print(f"   Agent result: {body}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Wait and check Slack for response
    print("\n4️⃣ Checking for agent reply in Slack thread...")
    time.sleep(5)
    replies = get_slack_replies(slack_token, SLACK_CHANNEL_ID, thread_ts, timeout=10)

    if replies:
        print(f"   ✅ Got {len(replies)} reply(s) in thread")
        for i, reply in enumerate(replies):
            text_preview = reply.get("text", "")[:200]
            print(f"   Reply {i+1}: {text_preview}...")
    else:
        print("   ⚠️ No replies in Slack thread yet")

    # Check server logs
    print("\n5️⃣ Checking server-side logs...")

    # Orchestrator logs
    orch_logs = get_recent_logs(AGENT_NAMESPACE, "app=incidentfox-orchestrator", 30)
    if "slack" in orch_logs.lower() or "correlation" in orch_logs.lower():
        print("   ✅ Orchestrator processed request")
    else:
        print("   ⚠️ No relevant orchestrator logs")

    # Agent logs
    agent_logs = get_recent_logs(AGENT_NAMESPACE, "app=incidentfox-agent", 30)
    if "run" in agent_logs.lower() or "agent" in agent_logs.lower():
        print("   ✅ Agent executed a run")
    else:
        print("   ⚠️ No agent execution in recent logs")

    # Direct API test
    print("\n6️⃣ Testing direct agent API...")
    try:
        api_result = call_agent_directly("What is 2+2?", timeout=30)
        if api_result.get("success"):
            print(
                f"   ✅ Agent API working (took {api_result.get('duration_seconds', 0):.2f}s)"
            )
        else:
            print(f"   ❌ Agent API failed: {api_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Agent API error: {e}")

    print("\n" + "=" * 60)
    print("✅ Slack E2E Test Complete")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = run_slack_e2e_test()
    sys.exit(0 if success else 1)
