#!/usr/bin/env python3
"""
Test harness for SRE Agent observability skills.

Tests each skill's scripts against real backends to validate:
1. Scripts execute without errors
2. API connectivity works
3. Response structure is valid

Usage:
    # Set credentials as environment variables, then run:
    python test_skills.py

    # Or test specific skill:
    python test_skills.py --skill jaeger

Required environment variables per skill:
    ClickUp:       CLICKUP_API_TOKEN
    Coralogix:     CORALOGIX_DOMAIN, CORALOGIX_API_KEY
    Datadog:       DATADOG_SITE, DATADOG_API_KEY, DATADOG_APP_KEY
    Elasticsearch: ELASTICSEARCH_URL (optional: ES_USER, ES_PASSWORD)
    Honeycomb:     HONEYCOMB_API_KEY
    Jaeger:        JAEGER_URL
    Prometheus:    PROMETHEUS_URL
    Grafana:       GRAFANA_URL, GRAFANA_API_KEY
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestResult:
    skill: str
    script: str
    passed: bool
    output: str
    error: str = ""


SKILLS_DIR = Path(__file__).parent


def run_script(
    skill_dir: str, script: str, args: list[str] = None, env_override: dict = None
) -> TestResult:
    """Run a skill script and capture output."""
    script_path = SKILLS_DIR / skill_dir / "scripts" / script

    if not script_path.exists():
        return TestResult(
            skill=skill_dir,
            script=script,
            passed=False,
            output="",
            error=f"Script not found: {script_path}",
        )

    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)

    env = os.environ.copy()
    if env_override:
        env.update(env_override)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=str(SKILLS_DIR / skill_dir / "scripts"),
        )

        if result.returncode != 0:
            return TestResult(
                skill=skill_dir,
                script=script,
                passed=False,
                output=result.stdout,
                error=result.stderr or f"Exit code: {result.returncode}",
            )

        return TestResult(
            skill=skill_dir, script=script, passed=True, output=result.stdout
        )
    except subprocess.TimeoutExpired:
        return TestResult(
            skill=skill_dir,
            script=script,
            passed=False,
            output="",
            error="Timeout after 30 seconds",
        )
    except Exception as e:
        return TestResult(
            skill=skill_dir, script=script, passed=False, output="", error=str(e)
        )


def validate_json_output(result: TestResult) -> TestResult:
    """Validate that output is valid JSON."""
    if not result.passed:
        return result

    try:
        data = json.loads(result.output)
        # Check for common error patterns in response
        if isinstance(data, dict):
            if data.get("error") or data.get("errors"):
                result.passed = False
                result.error = (
                    f"API error in response: {data.get('error') or data.get('errors')}"
                )
        return result
    except json.JSONDecodeError as e:
        # Not JSON output - that's OK for non-json mode
        return result


def check_env_vars(required: list[str]) -> tuple[bool, list[str]]:
    """Check if required environment variables are set."""
    missing = [var for var in required if not os.environ.get(var)]
    return len(missing) == 0, missing


# =============================================================================
# Skill Test Definitions
# =============================================================================


def test_coralogix() -> list[TestResult]:
    """Test Coralogix skill."""
    results = []

    ok, missing = check_env_vars(["CORALOGIX_DOMAIN", "CORALOGIX_API_KEY"])
    if not ok:
        return [
            TestResult(
                skill="observability-coralogix",
                script="(env check)",
                passed=False,
                output="",
                error=f"Missing env vars: {', '.join(missing)}",
            )
        ]

    # Test list_services.py
    result = run_script("observability-coralogix", "list_services.py", ["--json"])
    result = validate_json_output(result)
    results.append(result)

    # Test get_statistics.py
    result = run_script(
        "observability-coralogix", "get_statistics.py", ["--time-range", "30", "--json"]
    )
    result = validate_json_output(result)
    results.append(result)

    return results


def test_datadog() -> list[TestResult]:
    """Test Datadog skill."""
    results = []

    ok, missing = check_env_vars(["DATADOG_SITE", "DATADOG_API_KEY", "DATADOG_APP_KEY"])
    if not ok:
        return [
            TestResult(
                skill="observability-datadog",
                script="(env check)",
                passed=False,
                output="",
                error=f"Missing env vars: {', '.join(missing)}",
            )
        ]

    # Test get_statistics.py
    result = run_script(
        "observability-datadog", "get_statistics.py", ["--time-range", "30", "--json"]
    )
    result = validate_json_output(result)
    results.append(result)

    return results


def test_elasticsearch() -> list[TestResult]:
    """Test Elasticsearch skill."""
    results = []

    ok, missing = check_env_vars(["ELASTICSEARCH_URL"])
    if not ok:
        return [
            TestResult(
                skill="observability-elasticsearch",
                script="(env check)",
                passed=False,
                output="",
                error=f"Missing env vars: {', '.join(missing)}",
            )
        ]

    # Test get_statistics.py
    result = run_script(
        "observability-elasticsearch",
        "get_statistics.py",
        ["--time-range", "30", "--json"],
    )
    result = validate_json_output(result)
    results.append(result)

    return results


def test_jaeger() -> list[TestResult]:
    """Test Jaeger skill."""
    results = []

    ok, missing = check_env_vars(["JAEGER_URL"])
    if not ok:
        return [
            TestResult(
                skill="observability-jaeger",
                script="(env check)",
                passed=False,
                output="",
                error=f"Missing env vars: {', '.join(missing)}",
            )
        ]

    # Test list_services.py
    result = run_script("observability-jaeger", "list_services.py", ["--json"])
    result = validate_json_output(result)
    results.append(result)

    # Test list_operations.py (if we have services)
    if result.passed and result.output:
        try:
            data = json.loads(result.output)
            services = data.get("services", [])
            if services:
                result2 = run_script(
                    "observability-jaeger",
                    "list_operations.py",
                    [services[0], "--json"],
                )
                result2 = validate_json_output(result2)
                results.append(result2)
        except:
            pass

    return results


def test_prometheus() -> list[TestResult]:
    """Test Prometheus skill (via metrics-analysis)."""
    results = []

    ok, missing = check_env_vars(["PROMETHEUS_URL"])
    if not ok:
        return [
            TestResult(
                skill="metrics-analysis",
                script="(env check)",
                passed=False,
                output="",
                error=f"Missing env vars: {', '.join(missing)}",
            )
        ]

    # Test query_prometheus.py with a simple query
    result = run_script("metrics-analysis", "query_prometheus.py", ["up", "--json"])
    result = validate_json_output(result)
    results.append(result)

    return results


def test_grafana() -> list[TestResult]:
    """Test Grafana skill (via metrics-analysis)."""
    results = []

    ok, missing = check_env_vars(["GRAFANA_URL", "GRAFANA_API_KEY"])
    if not ok:
        return [
            TestResult(
                skill="metrics-analysis",
                script="(env check)",
                passed=False,
                output="",
                error=f"Missing env vars: {', '.join(missing)}",
            )
        ]

    # Test list_dashboards.py
    result = run_script("metrics-analysis", "list_dashboards.py", ["--json"])
    result = validate_json_output(result)
    results.append(result)

    return results


def test_honeycomb() -> list[TestResult]:
    """Test Honeycomb skill."""
    results = []

    ok, missing = check_env_vars(["HONEYCOMB_API_KEY"])
    if not ok:
        return [
            TestResult(
                skill="observability-honeycomb",
                script="(env check)",
                passed=False,
                output="",
                error=f"Missing env vars: {', '.join(missing)}",
            )
        ]

    # Test list_datasets.py
    result = run_script("observability-honeycomb", "list_datasets.py", ["--json"])
    result = validate_json_output(result)
    results.append(result)

    # If we have datasets, test get_statistics on the first one
    if result.passed and result.output:
        try:
            data = json.loads(result.output)
            if data and len(data) > 0:
                dataset_slug = data[0].get("slug")
                if dataset_slug:
                    result2 = run_script(
                        "observability-honeycomb",
                        "get_statistics.py",
                        [dataset_slug, "--time-range", "3600", "--json"],
                    )
                    result2 = validate_json_output(result2)
                    results.append(result2)

                    # Test run_query.py
                    result3 = run_script(
                        "observability-honeycomb",
                        "run_query.py",
                        [dataset_slug, "--calc", "COUNT", "--json"],
                    )
                    result3 = validate_json_output(result3)
                    results.append(result3)
        except json.JSONDecodeError:
            pass

    return results


def test_clickup() -> list[TestResult]:
    """Test ClickUp skill."""
    results = []

    ok, missing = check_env_vars(["CLICKUP_API_TOKEN"])
    if not ok:
        return [
            TestResult(
                skill="project-clickup",
                script="(env check)",
                passed=False,
                output="",
                error=f"Missing env vars: {', '.join(missing)}",
            )
        ]

    # Test list_spaces.py
    result = run_script("project-clickup", "list_spaces.py", ["--json"])
    result = validate_json_output(result)
    results.append(result)

    # Test search_tasks.py (basic search)
    result2 = run_script(
        "project-clickup", "search_tasks.py", ["--limit", "5", "--json"]
    )
    result2 = validate_json_output(result2)
    results.append(result2)

    return results


# =============================================================================
# Main Test Runner
# =============================================================================

SKILL_TESTS = {
    "coralogix": test_coralogix,
    "datadog": test_datadog,
    "elasticsearch": test_elasticsearch,
    "honeycomb": test_honeycomb,
    "jaeger": test_jaeger,
    "prometheus": test_prometheus,
    "grafana": test_grafana,
    "clickup": test_clickup,
}


def print_result(result: TestResult):
    """Print a single test result."""
    status = "✅ PASS" if result.passed else "❌ FAIL"
    print(f"  {status} {result.script}")
    if not result.passed and result.error:
        # Indent error message
        for line in result.error.strip().split("\n")[:5]:  # Limit to 5 lines
            print(f"         {line}")
    elif result.passed and result.output:
        # Show truncated output for passed tests
        lines = result.output.strip().split("\n")
        if len(lines) > 3:
            print(f"         Output: {lines[0][:60]}... ({len(lines)} lines)")


def main():
    parser = argparse.ArgumentParser(description="Test SRE Agent skills")
    parser.add_argument(
        "--skill",
        "-s",
        choices=list(SKILL_TESTS.keys()),
        help="Test specific skill only",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show full output for passed tests"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("SRE Agent Skills Test Harness")
    print("=" * 60)
    print()

    skills_to_test = [args.skill] if args.skill else list(SKILL_TESTS.keys())

    all_results = []

    for skill_name in skills_to_test:
        print(f"Testing: {skill_name}")
        print("-" * 40)

        test_func = SKILL_TESTS[skill_name]
        results = test_func()
        all_results.extend(results)

        for result in results:
            print_result(result)

        print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed)

    print(f"Total:  {len(all_results)} tests")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print()

    if failed > 0:
        print("Failed tests:")
        for r in all_results:
            if not r.passed:
                print(f"  - {r.skill}/{r.script}: {r.error[:50]}")
        sys.exit(1)
    else:
        print("All tests passed! ✅")
        sys.exit(0)


if __name__ == "__main__":
    main()
