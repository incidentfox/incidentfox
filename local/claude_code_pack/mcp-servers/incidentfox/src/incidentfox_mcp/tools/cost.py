"""AWS Cost Analysis Tools.

Tools for analyzing AWS costs and finding anomalies.
"""

import json
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

from ..utils.config import get_env


def _get_aws_session(region: str | None = None):
    """Get boto3 session."""
    import boto3
    from botocore.exceptions import NoCredentialsError

    region = region or get_env("AWS_REGION") or "us-east-1"

    try:
        session = boto3.Session(region_name=region)
        session.client("sts").get_caller_identity()
        return session
    except NoCredentialsError:
        raise RuntimeError("AWS credentials not configured")


def register_tools(mcp: FastMCP):
    """Register cost analysis tools."""

    @mcp.tool()
    def get_cost_summary(days: int = 30) -> str:
        """Get AWS cost summary for recent days.

        Args:
            days: Number of days to analyze (default: 30)

        Returns:
            JSON with cost breakdown by service.
        """
        try:
            session = _get_aws_session()
            ce = session.client(
                "ce", region_name="us-east-1"
            )  # Cost Explorer is global

            end = datetime.utcnow().date()
            start = end - timedelta(days=days)

            response = ce.get_cost_and_usage(
                TimePeriod={
                    "Start": start.isoformat(),
                    "End": end.isoformat(),
                },
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                GroupBy=[
                    {"Type": "DIMENSION", "Key": "SERVICE"},
                ],
            )

            # Aggregate costs by service
            service_costs = {}
            for result in response.get("ResultsByTime", []):
                for group in result.get("Groups", []):
                    service = group["Keys"][0]
                    cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                    service_costs[service] = service_costs.get(service, 0) + cost

            # Sort by cost
            sorted_costs = sorted(
                service_costs.items(), key=lambda x: x[1], reverse=True
            )

            total = sum(service_costs.values())

            return json.dumps(
                {
                    "period": f"Last {days} days",
                    "total_cost": round(total, 2),
                    "currency": "USD",
                    "top_services": [
                        {
                            "service": svc,
                            "cost": round(cost, 2),
                            "percentage": (
                                round(cost / total * 100, 1) if total > 0 else 0
                            ),
                        }
                        for svc, cost in sorted_costs[:10]
                    ],
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def get_cost_anomalies(days: int = 7) -> str:
        """Detect cost anomalies in AWS spending.

        Compares recent costs to historical baseline.

        Args:
            days: Number of recent days to check (default: 7)

        Returns:
            JSON with detected cost anomalies.
        """
        try:
            session = _get_aws_session()
            ce = session.client("ce", region_name="us-east-1")

            end = datetime.utcnow().date()
            recent_start = end - timedelta(days=days)
            baseline_start = end - timedelta(days=days * 4)  # 4x period for baseline

            # Get recent costs
            recent = ce.get_cost_and_usage(
                TimePeriod={
                    "Start": recent_start.isoformat(),
                    "End": end.isoformat(),
                },
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )

            # Get baseline costs
            baseline = ce.get_cost_and_usage(
                TimePeriod={
                    "Start": baseline_start.isoformat(),
                    "End": recent_start.isoformat(),
                },
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )

            # Calculate average daily cost per service for baseline
            baseline_daily = {}
            baseline_days = (recent_start - baseline_start).days
            for result in baseline.get("ResultsByTime", []):
                for group in result.get("Groups", []):
                    service = group["Keys"][0]
                    cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                    baseline_daily[service] = baseline_daily.get(service, 0) + cost

            for service in baseline_daily:
                baseline_daily[service] /= baseline_days

            # Calculate recent daily average
            recent_daily = {}
            for result in recent.get("ResultsByTime", []):
                for group in result.get("Groups", []):
                    service = group["Keys"][0]
                    cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                    recent_daily[service] = recent_daily.get(service, 0) + cost

            for service in recent_daily:
                recent_daily[service] /= days

            # Find anomalies (>50% increase)
            anomalies = []
            for service, recent_avg in recent_daily.items():
                baseline_avg = baseline_daily.get(service, 0)
                if baseline_avg > 1:  # Only check services with meaningful baseline
                    change_pct = (recent_avg - baseline_avg) / baseline_avg * 100
                    if change_pct > 50:  # >50% increase
                        anomalies.append(
                            {
                                "service": service,
                                "baseline_daily_avg": round(baseline_avg, 2),
                                "recent_daily_avg": round(recent_avg, 2),
                                "change_percent": round(change_pct, 1),
                                "estimated_monthly_impact": round(
                                    (recent_avg - baseline_avg) * 30, 2
                                ),
                            }
                        )

            anomalies.sort(key=lambda x: x["change_percent"], reverse=True)

            return json.dumps(
                {
                    "period_analyzed": f"Last {days} days vs previous {baseline_days} days",
                    "anomaly_count": len(anomalies),
                    "anomalies": anomalies,
                    "threshold": "50% increase from baseline",
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def get_ec2_rightsizing(region: str = "us-east-1") -> str:
        """Get EC2 rightsizing recommendations.

        Returns:
            JSON with instances that may be over/under-provisioned.
        """
        try:
            session = _get_aws_session(region)
            ce = session.client("ce", region_name="us-east-1")

            # Get rightsizing recommendations
            response = ce.get_rightsizing_recommendation(
                Service="AmazonEC2",
                Configuration={
                    "RecommendationTarget": "SAME_INSTANCE_FAMILY",
                    "BenefitsConsidered": True,
                },
            )

            recommendations = []
            for rec in response.get("RightsizingRecommendations", []):
                current = rec.get("CurrentInstance", {})
                modify = rec.get("ModifyRecommendationDetail", {})
                target = modify.get("TargetInstances", [{}])[0] if modify else {}

                recommendations.append(
                    {
                        "instance_id": current.get("ResourceId"),
                        "current_type": current.get("InstanceType"),
                        "recommended_type": target.get("InstanceType"),
                        "recommendation": rec.get("RightsizingType"),
                        "estimated_monthly_savings": float(
                            target.get("EstimatedMonthlySavings", {}).get("Value", 0)
                        ),
                        "cpu_utilization": current.get("ResourceUtilization", {})
                        .get("EC2ResourceUtilization", {})
                        .get("MaxCpuUtilizationPercentage"),
                    }
                )

            total_savings = sum(r["estimated_monthly_savings"] for r in recommendations)

            return json.dumps(
                {
                    "region": region,
                    "recommendation_count": len(recommendations),
                    "total_monthly_savings": round(total_savings, 2),
                    "recommendations": recommendations[:20],  # Limit output
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def get_daily_cost_trend(days: int = 14) -> str:
        """Get daily cost trend.

        Args:
            days: Number of days (default: 14)

        Returns:
            JSON with daily costs for trend analysis.
        """
        try:
            session = _get_aws_session()
            ce = session.client("ce", region_name="us-east-1")

            end = datetime.utcnow().date()
            start = end - timedelta(days=days)

            response = ce.get_cost_and_usage(
                TimePeriod={
                    "Start": start.isoformat(),
                    "End": end.isoformat(),
                },
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
            )

            daily_costs = []
            for result in response.get("ResultsByTime", []):
                date = result["TimePeriod"]["Start"]
                cost = float(result["Total"]["UnblendedCost"]["Amount"])
                daily_costs.append(
                    {
                        "date": date,
                        "cost": round(cost, 2),
                    }
                )

            # Calculate trend
            if len(daily_costs) >= 2:
                first_half = sum(
                    d["cost"] for d in daily_costs[: len(daily_costs) // 2]
                )
                second_half = sum(
                    d["cost"] for d in daily_costs[len(daily_costs) // 2 :]
                )
                trend = "increasing" if second_half > first_half else "decreasing"
            else:
                trend = "insufficient data"

            return json.dumps(
                {
                    "period": f"Last {days} days",
                    "trend": trend,
                    "daily_costs": daily_costs,
                    "average_daily": (
                        round(sum(d["cost"] for d in daily_costs) / len(daily_costs), 2)
                        if daily_costs
                        else 0
                    ),
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e)})
