#!/usr/bin/env python3
"""
IncidentFox AI SRE Agent - Performance Evaluation

This script runs comprehensive evaluation scenarios against the agent
using otel-demo fault injection and scores the results.

Target: ≥85 average score, <60s per scenario
"""

import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# Configuration
OTEL_NAMESPACE = "otel-demo"
AGENT_NAMESPACE = "incidentfox"
AWS_REGION = "us-west-2"

# Evaluation scenarios (sorted by tier - healthCheck runs FIRST before faults)
SCENARIOS = {
    # Tier 0: Control (run first)
    "healthCheck": {
        "tier": 0,
        "description": "Control - verify healthy system",
        "expected_root_cause": [
            "running",
            "healthy",
            "ok",
            "success",
            "connected",
            "listening",
            "no error",
            "no issues",
        ],
        "expected_affected": [],
        "expected_recommendation": [],
        "prompt": """Check the health of the cart pod in otel-demo namespace. Use list_pods to verify it exists and is running.""",
    },
    # Tier 1: Pod crash simulations (most reliable for testing)
    "cartCrash": {
        "tier": 1,
        "description": "Cart service crash (pod patch)",
        "expected_root_cause": [
            "cart",
            "crash",
            "fail",
            "error",
            "backoff",
            "CrashLoopBackOff",
            "SIMULATED",
            "exit",
        ],
        "expected_affected": ["cart", "checkout"],
        "expected_recommendation": ["fix", "restart", "check", "investigate", "code"],
        "prompt": """The cart service in otel-demo namespace has a problem. Diagnose it.""",
    },
    "paymentCrash": {
        "tier": 1,
        "description": "Payment service crash (pod patch)",
        "expected_root_cause": [
            "payment",
            "crash",
            "fail",
            "error",
            "backoff",
            "CrashLoopBackOff",
            "SIMULATED",
            "exit",
        ],
        "expected_affected": ["payment", "checkout"],
        "expected_recommendation": ["fix", "restart", "check", "investigate"],
        "prompt": """The payment service in otel-demo namespace is failing. Diagnose it.""",
    },
    "adCrash": {
        "tier": 1,
        "description": "Ad service crash (pod patch)",
        "expected_root_cause": [
            "ad",
            "crash",
            "fail",
            "error",
            "backoff",
            "CrashLoopBackOff",
            "SIMULATED",
            "exit",
        ],
        "expected_affected": ["ad", "frontend"],
        "expected_recommendation": ["fix", "restart", "check", "investigate"],
        "prompt": """The ad service in otel-demo namespace is failing. Diagnose it.""",
    },
    # Tier 2: Feature flag failures (application-level)
    "cartFailure": {
        "tier": 2,
        "flag": "cartFailure",
        "description": "Cart service failure (flagd)",
        "expected_root_cause": ["cart", "fail", "error", "flag"],
        "expected_affected": ["cart"],
        "expected_recommendation": ["flag", "disable", "check"],
        "prompt": """Users report cart issues in otel-demo. Check the cart service.""",
    },
    "paymentUnreachable": {
        "tier": 2,
        "flag": "paymentUnreachable",
        "description": "Payment service unreachable (flagd)",
        "expected_root_cause": ["payment", "unreachable", "timeout", "unavailable"],
        "expected_affected": ["payment", "checkout"],
        "expected_recommendation": ["restart", "network", "flag"],
        "prompt": """Payment transactions are failing in otel-demo. Investigate.""",
    },
    "adFailure": {
        "tier": 2,
        "flag": "adFailure",
        "description": "Ad service failure (flagd)",
        "expected_root_cause": ["ad", "fail", "error"],
        "expected_affected": ["ad", "frontend"],
        "expected_recommendation": ["fix", "restart", "flag"],
        "prompt": """Ads are not loading in otel-demo. Check the ad service.""",
    },
    "productCatalogFailure": {
        "tier": 2,
        "flag": "productCatalogFailure",
        "description": "Product catalog failure (flagd)",
        "expected_root_cause": ["product", "catalog", "fail", "error"],
        "expected_affected": ["product", "frontend"],
        "expected_recommendation": ["fix", "restart", "flag"],
        "prompt": """Product pages are showing errors in otel-demo. Investigate.""",
    },
    # Tier 3: Performance/Resource issues
    "adHighCpu": {
        "tier": 3,
        "flag": "adHighCpu",
        "description": "Ad service high CPU (flagd)",
        "expected_root_cause": ["ad", "cpu", "high", "slow", "resource"],
        "expected_affected": ["ad"],
        "expected_recommendation": ["scale", "resource", "optimize"],
        "prompt": """The ad service in otel-demo is very slow. Check resource usage.""",
    },
    "kafkaQueueProblems": {
        "tier": 3,
        "flag": "kafkaQueueProblems",
        "description": "Kafka queue lag (flagd)",
        "expected_root_cause": ["kafka", "queue", "lag", "delay", "slow"],
        "expected_affected": ["kafka", "messaging"],
        "expected_recommendation": ["scale", "consumer", "lag"],
        "prompt": """Message processing is delayed in otel-demo. Check Kafka.""",
    },
    "imageSlowLoad": {
        "tier": 3,
        "flag": "imageSlowLoad",
        "description": "Slow image loading (flagd)",
        "expected_root_cause": ["image", "slow", "load", "frontend"],
        "expected_affected": ["frontend", "image"],
        "expected_recommendation": ["cdn", "cache", "optimize"],
        "prompt": """Images are loading slowly in otel-demo frontend. Investigate.""",
    },
    # Tier 4: Memory/Advanced issues
    "emailMemoryLeak": {
        "tier": 4,
        "flag": "emailMemoryLeak",
        "description": "Email service memory leak (flagd)",
        "expected_root_cause": ["email", "memory", "leak", "oom"],
        "expected_affected": ["email"],
        "expected_recommendation": ["restart", "memory", "fix"],
        "prompt": """The email service in otel-demo may have a memory issue. Check it.""",
    },
    "paymentFailure50": {
        "tier": 4,
        "flag": "paymentFailure",
        "flag_variant": "50%",
        "description": "50% payment failures (flagd)",
        "expected_root_cause": ["payment", "fail", "intermittent", "partial", "50"],
        "expected_affected": ["payment", "checkout"],
        "expected_recommendation": ["investigate", "flag", "partial"],
        "prompt": """About half of payment transactions are failing in otel-demo. Diagnose.""",
    },
}


@dataclass
class EvalResult:
    scenario: str
    tier: int
    success: bool
    duration_seconds: float
    root_cause_score: int = 0  # /30
    evidence_score: int = 0  # /20
    impact_score: int = 0  # /15
    timeline_score: int = 0  # /15
    recommendation_score: int = 0  # /20
    total_score: int = 0  # /100
    agent_output: Dict[str, Any] = field(default_factory=dict)
    raw_response: str = ""
    error: Optional[str] = None
    notes: str = ""


def run_kubectl(args: List[str]) -> subprocess.CompletedProcess:
    """Run kubectl command."""
    return subprocess.run(["kubectl"] + args, capture_output=True, text=True)


def set_fault_flag(scenario_name: str, enabled: bool) -> bool:
    """Enable or disable a fault for testing."""
    scenario = SCENARIOS.get(scenario_name, {})

    # Tier 0: Control - no action needed
    if scenario.get("tier") == 0:
        return True

    # Tier 1: Pod crash simulations
    if scenario_name.endswith("Crash"):
        service = scenario_name.replace("Crash", "").lower()
        if enabled:
            # Simulate crash by patching deployment
            result = run_kubectl(
                [
                    "patch",
                    "deployment",
                    service,
                    "-n",
                    OTEL_NAMESPACE,
                    "--type=json",
                    "-p",
                    '[{"op": "replace", "path": "/spec/template/spec/containers/0/command", "value": ["/bin/sh", "-c", "echo SIMULATED CRASH; exit 1"]}]',
                ]
            )
            if result.returncode != 0:
                print(f"   ❌ Failed to inject crash: {result.stderr}")
                return False
            time.sleep(10)
            return True
        else:
            # Remove bad command
            run_kubectl(
                [
                    "patch",
                    "deployment",
                    service,
                    "-n",
                    OTEL_NAMESPACE,
                    "--type=json",
                    "-p",
                    '[{"op": "remove", "path": "/spec/template/spec/containers/0/command"}]',
                ]
            )
            time.sleep(10)
            return True

    # Tier 2-4: Feature flag faults
    flag_name = scenario.get("flag")
    if flag_name:
        variant = scenario.get("flag_variant", "on" if enabled else "off")
        if not enabled:
            variant = "off"

        # Get current config
        result = run_kubectl(
            [
                "get",
                "configmap",
                "flagd-config",
                "-n",
                OTEL_NAMESPACE,
                "-o",
                "jsonpath={.data.demo\\.flagd\\.json}",
            ]
        )
        if result.returncode != 0:
            print("   ❌ Failed to get flagd config")
            return False

        try:
            config = json.loads(result.stdout) if result.stdout else {"flags": {}}
        except json.JSONDecodeError:
            config = {"flags": {}}

        if flag_name in config.get("flags", {}):
            config["flags"][flag_name]["defaultVariant"] = variant

        # Apply patch
        patch = {"data": {"demo.flagd.json": json.dumps(config, indent=2)}}
        result = run_kubectl(
            [
                "patch",
                "configmap",
                "flagd-config",
                "-n",
                OTEL_NAMESPACE,
                "--type=merge",
                "-p",
                json.dumps(patch),
            ]
        )

        if result.returncode != 0:
            print(f"   ❌ Failed to patch flagd: {result.stderr}")
            return False

        # Restart flagd for changes to take effect
        run_kubectl(["rollout", "restart", "deployment/flagd", "-n", OTEL_NAMESPACE])
        time.sleep(8)
        return True

    print(f"   ⚠️  Unknown fault type: {scenario_name}")
    return False


def call_agent(prompt: str, timeout: int = 180) -> Dict[str, Any]:
    """Call the agent via port-forward."""
    # Kill stale port-forwards
    subprocess.run(["pkill", "-f", "kubectl port-forward.*18080"], capture_output=True)
    time.sleep(1)

    # Get agent pod
    result = run_kubectl(
        [
            "get",
            "pods",
            "-n",
            AGENT_NAMESPACE,
            "-l",
            "app=incidentfox-agent",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ]
    )
    pod_name = result.stdout.strip()
    if not pod_name:
        return {"error": "No agent pod found"}

    # Start port-forward
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
        time.sleep(4)

        import requests

        response = requests.post(
            "http://localhost:18080/agents/investigation_agent/run",
            json={
                "message": prompt,
                "context": {"target_namespace": OTEL_NAMESPACE},
                "timeout": timeout,
                "max_turns": 200,
            },
            timeout=timeout + 60,
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}
    finally:
        pf_proc.terminate()
        pf_proc.wait()


def score_result(scenario_config: Dict, agent_output: Dict) -> Dict[str, int]:
    """Score the agent output against expectations."""
    scores = {
        "root_cause": 0,
        "evidence": 0,
        "impact": 0,
        "timeline": 0,
        "recommendation": 0,
    }

    if not agent_output.get("success"):
        return scores

    # For healthCheck (tier 0), use different scoring since it's a control
    is_health_check = scenario_config.get("tier") == 0

    output = agent_output.get("output", {})
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except (ValueError, KeyError):
            output = {"summary": output}

    # Convert to lowercase string for matching
    output_str = json.dumps(output).lower()
    str(output.get("summary", "")).lower()
    root_cause = output.get("root_cause", {})
    if isinstance(root_cause, dict):
        root_cause_str = json.dumps(root_cause).lower()
    else:
        root_cause_str = str(root_cause).lower()

    recommendations = output.get("recommendations", [])
    if isinstance(recommendations, list):
        recommendations_str = " ".join([str(r).lower() for r in recommendations])
    else:
        recommendations_str = str(recommendations).lower()

    affected = output.get("affected_systems", [])
    timeline = output.get("timeline", [])

    # Score root cause (30 points)
    expected_rc = scenario_config.get("expected_root_cause", [])
    rc_matches = sum(1 for kw in expected_rc if kw.lower() in output_str)
    if rc_matches >= 3:
        scores["root_cause"] = 30
    elif rc_matches >= 2:
        scores["root_cause"] = 20
    elif rc_matches >= 1:
        scores["root_cause"] = 10

    # Bonus for specific root_cause field
    if root_cause and root_cause_str != "null" and root_cause_str != "none":
        scores["root_cause"] = min(30, scores["root_cause"] + 5)

    # Score evidence (20 points)
    if root_cause and isinstance(root_cause, dict):
        evidence = root_cause.get("evidence", [])
        if evidence and len(evidence) >= 2:
            scores["evidence"] = 20
        elif evidence:
            scores["evidence"] = 15
    if "log" in output_str or "error" in output_str or "event" in output_str:
        scores["evidence"] = max(scores["evidence"], 10)

    # Score impact (15 points)
    expected_affected = scenario_config.get("expected_affected", [])
    if affected and len(affected) >= 2:
        affected_str = " ".join([str(a).lower() for a in affected])
        impact_matches = sum(
            1 for kw in expected_affected if kw.lower() in affected_str
        )
        if impact_matches >= 2:
            scores["impact"] = 15
        elif impact_matches >= 1:
            scores["impact"] = 10
    elif "affect" in output_str or "impact" in output_str or "cascade" in output_str:
        scores["impact"] = 5

    # Score timeline (15 points)
    if timeline and len(timeline) >= 2:
        scores["timeline"] = 15
    elif timeline:
        scores["timeline"] = 10
    elif "time" in output_str or "when" in output_str or "started" in output_str:
        scores["timeline"] = 5

    # Score recommendations (20 points)
    expected_recs = scenario_config.get("expected_recommendation", [])
    if is_health_check:
        # For health checks, no recommendations is actually correct
        if not recommendations or len(recommendations) == 0:
            scores["recommendation"] = 20  # Perfect - healthy system needs no recs
        else:
            scores["recommendation"] = 10  # Still OK to have optional recs
        # Also give full marks for evidence (healthy = no evidence of problems needed)
        scores["evidence"] = 20
    else:
        rec_matches = sum(
            1
            for kw in expected_recs
            if kw.lower() in recommendations_str or kw.lower() in output_str
        )
        if rec_matches >= 2 and recommendations:
            scores["recommendation"] = 20
        elif rec_matches >= 1:
            scores["recommendation"] = 15
        elif recommendations:
            scores["recommendation"] = 10

    return scores


def run_scenario(scenario_name: str, scenario_config: Dict) -> EvalResult:
    """Run a single evaluation scenario."""
    print(f"\n{'='*60}")
    print(f"📋 Scenario: {scenario_name}")
    print(f"   Tier: {scenario_config['tier']}")
    print(f"   Description: {scenario_config['description']}")
    print("=" * 60)

    result = EvalResult(
        scenario=scenario_name,
        tier=scenario_config["tier"],
        success=False,
        duration_seconds=0,
    )

    # Step 1: Inject fault
    if scenario_name != "no_fault":
        print(f"\n1️⃣  Injecting fault: {scenario_name}")
        if not set_fault_flag(scenario_name, True):
            result.error = "Failed to inject fault"
            return result
        print("   ✅ Fault injected")
        time.sleep(5)  # Let fault take effect
    else:
        print("\n1️⃣  Control scenario - no fault injection")

    try:
        # Step 2: Run agent
        print("\n2️⃣  Running agent investigation...")
        start_time = time.time()

        agent_response = call_agent(scenario_config["prompt"], timeout=120)

        result.duration_seconds = time.time() - start_time
        result.raw_response = json.dumps(agent_response, indent=2)

        print(f"   ⏱️  Duration: {result.duration_seconds:.1f}s")

        if agent_response.get("error"):
            result.error = agent_response["error"]
            print(f"   ❌ Error: {result.error}")
        elif agent_response.get("success"):
            result.success = True
            result.agent_output = agent_response.get("output", {})
            print("   ✅ Agent completed successfully")
        else:
            result.error = agent_response.get("error", "Unknown error")
            print(f"   ⚠️  Agent did not succeed: {result.error}")

        # Step 3: Score results
        print("\n3️⃣  Scoring results...")
        scores = score_result(scenario_config, agent_response)

        result.root_cause_score = scores["root_cause"]
        result.evidence_score = scores["evidence"]
        result.impact_score = scores["impact"]
        result.timeline_score = scores["timeline"]
        result.recommendation_score = scores["recommendation"]
        result.total_score = sum(scores.values())

        print(f"   Root Cause:     {result.root_cause_score}/30")
        print(f"   Evidence:       {result.evidence_score}/20")
        print(f"   Impact:         {result.impact_score}/15")
        print(f"   Timeline:       {result.timeline_score}/15")
        print(f"   Recommendation: {result.recommendation_score}/20")
        print("   ────────────────────────")
        print(f"   TOTAL:          {result.total_score}/100")

        # Print agent output summary
        if result.agent_output:
            output = result.agent_output
            if isinstance(output, dict):
                summary = output.get("summary", "No summary")
                print(f"\n   📝 Summary: {summary[:200]}...")

    finally:
        # Step 4: Clear fault
        if scenario_name != "no_fault":
            print("\n4️⃣  Clearing fault...")
            set_fault_flag(scenario_name, False)
            print("   ✅ Fault cleared")

    return result


def run_evaluation(scenarios_to_run: Optional[List[str]] = None):
    """Run full evaluation suite."""
    print("\n" + "=" * 70)
    print("🌙 IncidentFox AI SRE Agent - Performance Evaluation")
    print("=" * 70)
    print(f"Started: {datetime.now().isoformat()}")
    print("Target: ≥85 average score, <60s per scenario")
    print("=" * 70)

    if scenarios_to_run is None:
        # Sort by tier (healthCheck tier=0 runs first)
        scenarios_to_run = sorted(SCENARIOS.keys(), key=lambda k: SCENARIOS[k]["tier"])

    results: List[EvalResult] = []

    for scenario_name in scenarios_to_run:
        if scenario_name not in SCENARIOS:
            print(f"⚠️  Unknown scenario: {scenario_name}")
            continue

        result = run_scenario(scenario_name, SCENARIOS[scenario_name])
        results.append(result)

        # Brief pause between scenarios
        time.sleep(3)

    # Generate summary
    print("\n" + "=" * 70)
    print("📊 EVALUATION SUMMARY")
    print("=" * 70)

    print("\n| Scenario | Tier | Score | Time | Status |")
    print("|----------|------|-------|------|--------|")

    total_score = 0
    total_time = 0
    passed = 0

    for r in results:
        status = "✅" if r.total_score >= 85 else "🟡" if r.total_score >= 70 else "❌"
        print(
            f"| {r.scenario[:20]:<20} | {r.tier} | {r.total_score:>3}/100 | {r.duration_seconds:>5.1f}s | {status} |"
        )
        total_score += r.total_score
        total_time += r.duration_seconds
        if r.total_score >= 85:
            passed += 1

    avg_score = total_score / len(results) if results else 0
    avg_time = total_time / len(results) if results else 0

    print("\n" + "-" * 70)
    print(f"Average Score: {avg_score:.1f}/100 (target: ≥85)")
    print(f"Average Time:  {avg_time:.1f}s (target: <60s)")
    print(
        f"Pass Rate:     {passed}/{len(results)} ({100*passed/len(results) if results else 0:.0f}%)"
    )

    # Determine overall status
    if avg_score >= 85 and avg_time < 60:
        print("\n🟢 ENTERPRISE READY")
    elif avg_score >= 70:
        print("\n🟡 NEEDS IMPROVEMENT")
    else:
        print("\n🔴 NOT READY")

    # Save results
    results_file = f"eval_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2, default=str)
    print(f"\n📁 Results saved to: {results_file}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="IncidentFox Agent Evaluation")
    parser.add_argument("--scenarios", nargs="+", help="Specific scenarios to run")
    parser.add_argument("--tier", type=int, help="Run only scenarios from this tier")
    parser.add_argument(
        "--quick", action="store_true", help="Run only Tier 1 scenarios"
    )

    args = parser.parse_args()

    scenarios = None
    if args.scenarios:
        scenarios = args.scenarios
    elif args.tier:
        scenarios = [
            name for name, cfg in SCENARIOS.items() if cfg["tier"] == args.tier
        ]
    elif args.quick:
        scenarios = [name for name, cfg in SCENARIOS.items() if cfg["tier"] == 1]

    run_evaluation(scenarios)
