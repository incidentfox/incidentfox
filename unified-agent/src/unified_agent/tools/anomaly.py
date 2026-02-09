"""
Anomaly detection and time series analysis tools.

Provides statistical anomaly detection and Prophet-based forecasting
for correlating metrics with incident root causes.

Prophet is used when available for:
- Seasonal anomaly detection
- Trend decomposition
- Change point detection with uncertainty
"""

from __future__ import annotations

import json
import statistics
from typing import Any

import os

from ..core.agent import function_tool
from . import register_tool


logger = logging.getLogger(__name__)


def _is_prophet_available() -> bool:
    """Check if Prophet is installed."""
    try:
        from prophet import Prophet

        return True
    except ImportError:
        return False


def _calculate_zscore(values: list[float], current: float) -> float:
    """Calculate Z-score for a value against historical data."""
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    if stdev == 0:
        return 0.0
    return (current - mean) / stdev


def _calculate_percentile(values: list[float], current: float) -> float:
    """Calculate what percentile a value falls into."""
    if not values:
        return 50.0
    below = sum(1 for v in values if v < current)
    return (below / len(values)) * 100


def _detect_spike(values: list[float], threshold_stdev: float = 2.0) -> str:
    """Detect spikes in time series data."""
    if len(values) < 3:
        return []

    mean = statistics.mean(values)
    stdev = statistics.stdev(values) if len(values) > 1 else 0
    threshold = mean + (threshold_stdev * stdev)

    anomalies = []
    for i, value in enumerate(values):
        if value > threshold:
            anomalies.append(
                {
                    "index": i,
                    "value": value,
                    "threshold": threshold,
                    "deviation": (value - mean) / stdev if stdev > 0 else 0,
                    "type": "spike",
                }
            )
    return anomalies


def _detect_drop(values: list[float], threshold_stdev: float = 2.0) -> str:
    """Detect sudden drops in time series data."""
    if len(values) < 3:
        return []

    mean = statistics.mean(values)
    stdev = statistics.stdev(values) if len(values) > 1 else 0
    threshold = mean - (threshold_stdev * stdev)

    anomalies = []
    for i, value in enumerate(values):
        if value < threshold:
            anomalies.append(
                {
                    "index": i,
                    "value": value,
                    "threshold": threshold,
                    "deviation": (mean - value) / stdev if stdev > 0 else 0,
                    "type": "drop",
                }
            )
    return anomalies


def _calculate_trend(values: list[float]) -> str:
    """Calculate trend direction and strength."""
    if len(values) < 2:
        return {"direction": "stable", "strength": 0.0}

    # Simple linear regression
    n = len(values)
    x_mean = (n - 1) / 2
    y_mean = statistics.mean(values)

    numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    slope = numerator / denominator if denominator != 0 else 0

    # Normalize slope relative to mean
    relative_slope = (slope / y_mean * 100) if y_mean != 0 else 0

    if abs(relative_slope) < 1:
        direction = "stable"
    elif relative_slope > 0:
        direction = "increasing"
    else:
        direction = "decreasing"

    return {
        "direction": direction,
        "slope": slope,
        "relative_change_per_point": relative_slope,
        "strength": abs(relative_slope),
    }


@function_tool
def detect_anomalies(
    values: str,
    timestamps: str = "",
    threshold_stdev: float = 2.0,
    metric_name: str = "metric",
) -> str:
    """
    Detect anomalies in time series data using statistical methods.

    Use cases:
    - Find spikes in latency, error rates, CPU usage
    - Detect sudden drops in throughput, availability
    - Identify unusual patterns that correlate with incidents

    Args:
        values: JSON array of numeric values (e.g., "[1.2, 1.3, 5.8, 1.1, 1.2]")
        timestamps: Optional JSON array of timestamps
        threshold_stdev: Standard deviations for anomaly (default 2.0)
        metric_name: Name of the metric for reporting

    Returns:
        JSON with anomalies, statistics, and severity assessment
    """
    try:
        data = json.loads(values)
        if not isinstance(data, list) or len(data) < 3:
            return json.dumps(
                {
                    "ok": False,
                    "error": "Need at least 3 data points",
                    "metric": metric_name,
                }
            )

        # Convert to floats
        float_values = [float(v) for v in data]

        # Calculate statistics
        mean = statistics.mean(float_values)
        stdev = statistics.stdev(float_values) if len(float_values) > 1 else 0
        min_val = min(float_values)
        max_val = max(float_values)

        # Detect anomalies
        spikes = _detect_spike(float_values, threshold_stdev)
        drops = _detect_drop(float_values, threshold_stdev)
        trend = _calculate_trend(float_values)

        # Assess severity
        all_anomalies = spikes + drops
        if len(all_anomalies) > len(float_values) * 0.2:
            severity = "high"
        elif len(all_anomalies) > 0:
            max_deviation = max(
                [a.get("deviation", 0) for a in all_anomalies], default=0
            )
            if max_deviation > 3:
                severity = "high"
            elif max_deviation > 2:
                severity = "medium"
            else:
                severity = "low"
        else:
            severity = "none"

        result = {
            "ok": True,
            "metric": metric_name,
            "statistics": {
                "mean": round(mean, 4),
                "stdev": round(stdev, 4),
                "min": round(min_val, 4),
                "max": round(max_val, 4),
                "count": len(float_values),
            },
            "trend": trend,
            "anomalies": {
                "spikes": spikes,
                "drops": drops,
                "total_count": len(all_anomalies),
            },
            "severity": severity,
            "recommendation": _get_anomaly_recommendation(
                severity, trend, spikes, drops
            ),
        }

        logger.info(
            "anomaly_detection_completed",
            metric=metric_name,
            anomalies=len(all_anomalies),
        )
        return json.dumps(result)

    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
    except Exception as e:
        logger.error("anomaly_detection_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


def _get_anomaly_recommendation(
    severity: str, trend: dict, spikes: list, drops: list
) -> str:
    """Generate recommendation based on anomaly analysis."""
    if severity == "none":
        if trend["direction"] == "increasing":
            return f"No anomalies detected. Metric is trending upward ({trend['strength']:.1f}% per point). Monitor for continued growth."
        elif trend["direction"] == "decreasing":
            return "No anomalies detected. Metric is trending downward. Verify this is expected."
        return "No anomalies detected. Metric is stable."

    if spikes and not drops:
        return f"Detected {len(spikes)} spike(s). Check for traffic bursts, resource contention, or upstream issues."
    elif drops and not spikes:
        return f"Detected {len(drops)} drop(s). Check for failures, capacity issues, or dependency problems."
    else:
        return f"Detected {len(spikes)} spike(s) and {len(drops)} drop(s). Metric is unstable - investigate root cause."


@function_tool
def correlate_metrics(
    metric_a_values: str,
    metric_b_values: str,
    metric_a_name: str = "metric_a",
    metric_b_name: str = "metric_b",
) -> str:
    """
    Calculate correlation between two metrics to find relationships.

    Use cases:
    - Find if CPU spikes correlate with latency increases
    - Check if error rate correlates with request volume
    - Identify cascading effects between services

    Args:
        metric_a_values: JSON array of values for first metric
        metric_b_values: JSON array of values for second metric
        metric_a_name: Name of first metric
        metric_b_name: Name of second metric

    Returns:
        JSON with correlation coefficient and interpretation
    """
    try:
        data_a = [float(v) for v in json.loads(metric_a_values)]
        data_b = [float(v) for v in json.loads(metric_b_values)]

        if len(data_a) != len(data_b):
            return json.dumps(
                {
                    "ok": False,
                    "error": f"Metric arrays must be same length ({len(data_a)} vs {len(data_b)})",
                }
            )

        if len(data_a) < 3:
            return json.dumps({"ok": False, "error": "Need at least 3 data points"})

        # Calculate Pearson correlation
        n = len(data_a)
        mean_a = statistics.mean(data_a)
        mean_b = statistics.mean(data_b)

        numerator = sum((data_a[i] - mean_a) * (data_b[i] - mean_b) for i in range(n))
        denom_a = sum((v - mean_a) ** 2 for v in data_a) ** 0.5
        denom_b = sum((v - mean_b) ** 2 for v in data_b) ** 0.5

        if denom_a == 0 or denom_b == 0:
            correlation = 0.0
        else:
            correlation = numerator / (denom_a * denom_b)

        # Interpret correlation
        abs_corr = abs(correlation)
        if abs_corr > 0.8:
            strength = "strong"
        elif abs_corr > 0.5:
            strength = "moderate"
        elif abs_corr > 0.3:
            strength = "weak"
        else:
            strength = "negligible"

        direction = "positive" if correlation > 0 else "negative"

        # Generate insight
        if strength in ["strong", "moderate"]:
            if direction == "positive":
                insight = f"When {metric_a_name} increases, {metric_b_name} also tends to increase. These metrics are likely related."
            else:
                insight = f"When {metric_a_name} increases, {metric_b_name} tends to decrease. These metrics may have an inverse relationship."
        else:
            insight = f"No significant correlation found between {metric_a_name} and {metric_b_name}."

        result = {
            "ok": True,
            "correlation": round(correlation, 4),
            "strength": strength,
            "direction": direction,
            "metrics": [metric_a_name, metric_b_name],
            "insight": insight,
            "data_points": n,
        }

        logger.info(
            "correlation_calculated",
            metrics=[metric_a_name, metric_b_name],
            correlation=correlation,
        )
        return json.dumps(result)

    except Exception as e:
        logger.error("correlation_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def find_change_point(values: str, metric_name: str = "metric") -> str:
    """
    Find significant change points in time series data.

    Use cases:
    - Identify when a deployment caused a change in behavior
    - Find when an incident started affecting metrics
    - Detect regime changes in system behavior

    Args:
        values: JSON array of numeric values
        metric_name: Name of the metric

    Returns:
        JSON with detected change points and before/after analysis
    """
    try:
        data = [float(v) for v in json.loads(values)]

        if len(data) < 6:
            return json.dumps({"ok": False, "error": "Need at least 6 data points"})

        # Simple change point detection using CUSUM-like approach
        n = len(data)
        overall_mean = statistics.mean(data)

        # Calculate cumulative sum of deviations
        cusum = []
        cumulative = 0
        for v in data:
            cumulative += v - overall_mean
            cusum.append(cumulative)

        # Find point with maximum absolute CUSUM
        max_abs_cusum = 0
        change_point_idx = -1
        for i, c in enumerate(cusum):
            if abs(c) > max_abs_cusum:
                max_abs_cusum = abs(c)
                change_point_idx = i

        # Analyze before and after
        if change_point_idx > 0 and change_point_idx < n - 1:
            before = data[: change_point_idx + 1]
            after = data[change_point_idx + 1 :]

            before_mean = statistics.mean(before)
            after_mean = statistics.mean(after)
            change_magnitude = (
                ((after_mean - before_mean) / before_mean * 100)
                if before_mean != 0
                else 0
            )

            # Determine significance
            before_stdev = statistics.stdev(before) if len(before) > 1 else 0
            if before_stdev > 0:
                significance = abs(after_mean - before_mean) / before_stdev
            else:
                significance = 0

            is_significant = significance > 2.0

            result = {
                "ok": True,
                "change_detected": is_significant,
                "change_point": {
                    "index": change_point_idx,
                    "significance": round(significance, 2),
                },
                "before": {
                    "mean": round(before_mean, 4),
                    "count": len(before),
                },
                "after": {
                    "mean": round(after_mean, 4),
                    "count": len(after),
                },
                "change_magnitude_percent": round(change_magnitude, 2),
                "metric": metric_name,
                "insight": _get_change_insight(
                    is_significant, change_magnitude, metric_name
                ),
            }
        else:
            result = {
                "ok": True,
                "change_detected": False,
                "metric": metric_name,
                "insight": f"No significant change point detected in {metric_name}.",
            }

        logger.info("change_point_analysis_completed", metric=metric_name)
        return json.dumps(result)

    except Exception as e:
        logger.error("change_point_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


def _get_change_insight(
    is_significant: bool, magnitude: float, metric_name: str
) -> str:
    """Generate insight for change point detection."""
    if not is_significant:
        return f"No significant change point detected in {metric_name}."

    direction = "increased" if magnitude > 0 else "decreased"
    return f"{metric_name} {direction} by {abs(magnitude):.1f}% at the change point. Investigate what happened at this time (deployment, config change, incident)."


@function_tool
def forecast_metric(
    values: str, periods_ahead: int = 5, metric_name: str = "metric"
) -> str:
    """
    Simple forecast of future metric values using linear regression.

    Note: For production use with seasonality, consider Prophet.
    This provides a quick linear extrapolation.

    Use cases:
    - Predict when a resource will be exhausted
    - Estimate future load based on trends
    - Project error rates

    Args:
        values: JSON array of historical values
        periods_ahead: Number of future periods to forecast
        metric_name: Name of the metric

    Returns:
        JSON with forecasted values and confidence bounds
    """
    try:
        data = [float(v) for v in json.loads(values)]

        if len(data) < 5:
            return json.dumps(
                {"ok": False, "error": "Need at least 5 data points for forecasting"}
            )

        n = len(data)

        # Linear regression
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(data)

        numerator = sum((i - x_mean) * (data[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        slope = numerator / denominator if denominator != 0 else 0
        intercept = y_mean - slope * x_mean

        # Calculate residual standard error for confidence bounds
        residuals = [data[i] - (intercept + slope * i) for i in range(n)]
        rse = statistics.stdev(residuals) if len(residuals) > 1 else 0

        # Forecast
        forecasts = []
        for p in range(1, periods_ahead + 1):
            future_idx = n - 1 + p
            predicted = intercept + slope * future_idx

            forecasts.append(
                {
                    "period": p,
                    "predicted": round(predicted, 4),
                    "lower_bound": round(predicted - 2 * rse, 4),
                    "upper_bound": round(predicted + 2 * rse, 4),
                }
            )

        # Trend assessment
        final_forecast = forecasts[-1]["predicted"] if forecasts else y_mean
        pct_change = (
            ((final_forecast - data[-1]) / data[-1] * 100) if data[-1] != 0 else 0
        )

        result = {
            "ok": True,
            "metric": metric_name,
            "current_value": data[-1],
            "forecasts": forecasts,
            "trend": {
                "slope_per_period": round(slope, 4),
                "forecast_change_percent": round(pct_change, 2),
            },
            "confidence": "linear_extrapolation",
            "warning": _get_forecast_warning(data, forecasts, metric_name),
        }

        logger.info("forecast_completed", metric=metric_name, periods=periods_ahead)
        return json.dumps(result)

    except Exception as e:
        logger.error("forecast_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


def _get_forecast_warning(
    historical: list[float], forecasts: list[dict], metric_name: str
) -> str | None:
    """Generate warning if forecast indicates a problem."""
    if not forecasts:
        return None

    current = historical[-1]
    final = forecasts[-1]["predicted"]

    # Check for concerning trends
    if final > current * 2:
        return f"Warning: {metric_name} is projected to double. Consider scaling or optimization."
    elif final < current * 0.5:
        return f"Warning: {metric_name} is projected to drop significantly. Verify this is expected."
    elif final < 0:
        return "Warning: Forecast shows negative values which may be unrealistic."

    return None


@function_tool
def analyze_metric_distribution(values: str, metric_name: str = "metric") -> str:
    """
    Analyze the distribution of metric values for deeper insights.

    Use cases:
    - Understand if latency is normally distributed or has long tail
    - Identify bimodal distributions (two different behaviors)
    - Calculate percentiles for SLO analysis

    Args:
        values: JSON array of numeric values
        metric_name: Name of the metric

    Returns:
        JSON with distribution analysis, percentiles, and insights
    """
    try:
        data = [float(v) for v in json.loads(values)]

        if len(data) < 10:
            return json.dumps(
                {
                    "ok": False,
                    "error": "Need at least 10 data points for distribution analysis",
                }
            )

        sorted_data = sorted(data)
        n = len(data)

        # Calculate percentiles
        @function_tool
        def percentile(p):
            idx = int(n * p / 100)
            return sorted_data[min(idx, n - 1)]

        p50 = percentile(50)
        p90 = percentile(90)
        p95 = percentile(95)
        p99 = percentile(99)

        mean = statistics.mean(data)
        stdev = statistics.stdev(data)

        # Check for skewness (simplified)
        skewness = (mean - p50) / stdev if stdev > 0 else 0

        if abs(skewness) < 0.5:
            distribution_type = "symmetric"
        elif skewness > 0:
            distribution_type = "right_skewed"  # Long tail of high values
        else:
            distribution_type = "left_skewed"  # Long tail of low values

        # Check for potential bimodality
        # Simplified: if p50 is far from mean relative to stdev
        potential_bimodal = abs(mean - p50) > stdev * 0.5

        # Long tail analysis
        p99_to_p50_ratio = p99 / p50 if p50 > 0 else 0
        has_long_tail = p99_to_p50_ratio > 3

        result = {
            "ok": True,
            "metric": metric_name,
            "count": n,
            "percentiles": {
                "p50": round(p50, 4),
                "p90": round(p90, 4),
                "p95": round(p95, 4),
                "p99": round(p99, 4),
            },
            "statistics": {
                "mean": round(mean, 4),
                "stdev": round(stdev, 4),
                "min": round(sorted_data[0], 4),
                "max": round(sorted_data[-1], 4),
            },
            "distribution": {
                "type": distribution_type,
                "potential_bimodal": potential_bimodal,
                "has_long_tail": has_long_tail,
                "p99_to_p50_ratio": round(p99_to_p50_ratio, 2),
            },
            "slo_insight": _get_slo_insight(p50, p95, p99, metric_name),
        }

        logger.info("distribution_analysis_completed", metric=metric_name)
        return json.dumps(result)

    except Exception as e:
        logger.error("distribution_analysis_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


def _get_slo_insight(p50: float, p95: float, p99: float, metric_name: str) -> str:
    """Generate SLO-related insight."""
    p95_vs_p50 = p95 / p50 if p50 > 0 else 1
    p99_vs_p95 = p99 / p95 if p95 > 0 else 1

    if p99_vs_p95 > 2:
        return f"p99 is {p99_vs_p95:.1f}x higher than p95, indicating occasional extreme outliers. Consider investigating these edge cases."
    elif p95_vs_p50 > 2:
        return f"p95 is {p95_vs_p50:.1f}x higher than p50, showing significant variance. The long tail may impact user experience."
    else:
        return f"Distribution is relatively tight. p95={p95:.2f}, p99={p99:.2f}."


# =============================================================================
# Prophet-based Anomaly Detection (requires `prophet` package)
# =============================================================================


@function_tool
def prophet_detect_anomalies(
    values: str,
    timestamps: str,
    metric_name: str = "metric",
    interval_width: float = 0.95,
    seasonality_mode: str = "additive",
) -> str:
    """
    Detect anomalies using Facebook Prophet with seasonality awareness.

    Prophet excels at:
    - Detecting anomalies that account for daily/weekly/yearly patterns
    - Handling missing data gracefully
    - Providing uncertainty intervals for anomaly detection

    Use cases:
    - Detect unusual traffic patterns accounting for daily cycles
    - Find anomalies in metrics with weekly seasonality
    - Identify deviations from expected seasonal behavior

    Args:
        values: JSON array of metric values
        timestamps: JSON array of ISO timestamps (must match values length)
        metric_name: Name of the metric
        interval_width: Confidence interval (0.95 = 95%, higher = fewer anomalies)
        seasonality_mode: "additive" or "multiplicative"

    Returns:
        JSON with anomalies, trend, seasonality components, and forecast
    """
    if not _is_prophet_available():
        return json.dumps(
            {
                "ok": False,
                "error": "Prophet not installed. Install with: pip install prophet",
                "fallback": "Use detect_anomalies() for basic statistical detection",
            }
        )

    try:
        import pandas as pd
        from prophet import Prophet

        # Parse inputs
        values_list = json.loads(values)
        timestamps_list = json.loads(timestamps)

        if len(values_list) != len(timestamps_list):
            return json.dumps(
                {
                    "ok": False,
                    "error": f"Values ({len(values_list)}) and timestamps ({len(timestamps_list)}) must have same length",
                }
            )

        if len(values_list) < 10:
            return json.dumps(
                {"ok": False, "error": "Need at least 10 data points for Prophet"}
            )

        # Create DataFrame for Prophet (requires 'ds' and 'y' columns)
        df = pd.DataFrame(
            {
                "ds": pd.to_datetime(timestamps_list),
                "y": [float(v) for v in values_list],
            }
        )

        # Fit Prophet model
        model = Prophet(
            interval_width=interval_width,
            seasonality_mode=seasonality_mode,
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=False,  # Usually not enough data
        )

        # Suppress Prophet's verbose output
        import logging

        logging.getLogger("prophet").setLevel(logging.WARNING)

        model.fit(df)

        # Get predictions with uncertainty
        forecast = model.predict(df)

        # Detect anomalies: points outside the confidence interval
        df["yhat"] = forecast["yhat"]
        df["yhat_lower"] = forecast["yhat_lower"]
        df["yhat_upper"] = forecast["yhat_upper"]
        df["anomaly"] = (df["y"] < df["yhat_lower"]) | (df["y"] > df["yhat_upper"])
        df["residual"] = df["y"] - df["yhat"]

        # Get anomalies
        anomalies = []
        for idx, row in df[df["anomaly"]].iterrows():
            direction = "above" if row["y"] > row["yhat_upper"] else "below"
            deviation = (
                abs(row["residual"]) / (row["yhat_upper"] - row["yhat_lower"])
                if (row["yhat_upper"] - row["yhat_lower"]) > 0
                else 0
            )

            anomalies.append(
                {
                    "timestamp": row["ds"].isoformat(),
                    "actual": round(float(row["y"]), 4),
                    "expected": round(float(row["yhat"]), 4),
                    "lower_bound": round(float(row["yhat_lower"]), 4),
                    "upper_bound": round(float(row["yhat_upper"]), 4),
                    "direction": direction,
                    "deviation_strength": round(deviation, 2),
                }
            )

        # Calculate severity
        if len(anomalies) > len(values_list) * 0.2:
            severity = "high"
        elif len(anomalies) > len(values_list) * 0.1:
            severity = "medium"
        elif len(anomalies) > 0:
            severity = "low"
        else:
            severity = "none"

        # Get trend info
        trend_start = float(forecast["trend"].iloc[0])
        trend_end = float(forecast["trend"].iloc[-1])
        trend_change_pct = (
            ((trend_end - trend_start) / trend_start * 100) if trend_start != 0 else 0
        )

        result = {
            "ok": True,
            "metric": metric_name,
            "model": "prophet",
            "data_points": len(values_list),
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
            "severity": severity,
            "trend": {
                "start": round(trend_start, 4),
                "end": round(trend_end, 4),
                "change_percent": round(trend_change_pct, 2),
                "direction": (
                    "increasing"
                    if trend_change_pct > 1
                    else "decreasing" if trend_change_pct < -1 else "stable"
                ),
            },
            "seasonality_mode": seasonality_mode,
            "confidence_interval": interval_width,
            "insight": _get_prophet_insight(
                anomalies, trend_change_pct, severity, metric_name
            ),
        }

        logger.info(
            "prophet_anomaly_detection_completed",
            metric=metric_name,
            anomalies=len(anomalies),
            severity=severity,
        )
        return json.dumps(result)

    except Exception as e:
        logger.error("prophet_anomaly_detection_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


def _get_prophet_insight(
    anomalies: list[dict], trend_pct: float, severity: str, metric_name: str
) -> str:
    """Generate insight from Prophet analysis."""
    parts = []

    if severity == "none":
        parts.append(
            f"No anomalies detected in {metric_name}. Values are within expected seasonal patterns."
        )
    else:
        above = sum(1 for a in anomalies if a.get("direction") == "above")
        below = len(anomalies) - above

        if above > below:
            parts.append(
                f"Detected {len(anomalies)} anomalies, mostly ABOVE expected ({above} high, {below} low)."
            )
        elif below > above:
            parts.append(
                f"Detected {len(anomalies)} anomalies, mostly BELOW expected ({below} low, {above} high)."
            )
        else:
            parts.append(f"Detected {len(anomalies)} anomalies (mixed directions).")

    if abs(trend_pct) > 5:
        direction = "increasing" if trend_pct > 0 else "decreasing"
        parts.append(f"Overall trend is {direction} by {abs(trend_pct):.1f}%.")

    return " ".join(parts)


@function_tool
def prophet_forecast(
    values: str,
    timestamps: str,
    periods_ahead: int = 10,
    metric_name: str = "metric",
    include_history: bool = False,
) -> str:
    """
    Forecast future values using Facebook Prophet with uncertainty bounds.

    Prophet provides:
    - Seasonality-aware forecasting
    - Uncertainty intervals that widen over time
    - Trend and seasonality decomposition

    Use cases:
    - Predict capacity needs (when will disk fill up?)
    - Forecast traffic for capacity planning
    - Predict when SLO will be breached

    Args:
        values: JSON array of metric values
        timestamps: JSON array of ISO timestamps
        periods_ahead: Number of future periods to forecast
        metric_name: Name of the metric
        include_history: Include historical fit in response

    Returns:
        JSON with forecast, uncertainty bounds, and components
    """
    if not _is_prophet_available():
        return json.dumps(
            {
                "ok": False,
                "error": "Prophet not installed. Install with: pip install prophet",
                "fallback": "Use forecast_metric() for basic linear forecasting",
            }
        )

    try:
        import pandas as pd
        from prophet import Prophet

        values_list = json.loads(values)
        timestamps_list = json.loads(timestamps)

        if len(values_list) != len(timestamps_list):
            return json.dumps(
                {"ok": False, "error": "Values and timestamps must have same length"}
            )

        if len(values_list) < 10:
            return json.dumps({"ok": False, "error": "Need at least 10 data points"})

        df = pd.DataFrame(
            {
                "ds": pd.to_datetime(timestamps_list),
                "y": [float(v) for v in values_list],
            }
        )

        # Determine frequency
        time_diffs = df["ds"].diff().dropna()
        median_diff = time_diffs.median()

        if median_diff <= pd.Timedelta(minutes=5):
            freq = "min"
        elif median_diff <= pd.Timedelta(hours=2):
            freq = "h"
        else:
            freq = "D"

        # Fit model
        model = Prophet(
            interval_width=0.80,  # 80% confidence for forecasts
            daily_seasonality=True,
            weekly_seasonality=True,
        )

        import logging

        logging.getLogger("prophet").setLevel(logging.WARNING)

        model.fit(df)

        # Create future dataframe
        future = model.make_future_dataframe(periods=periods_ahead, freq=freq)
        forecast = model.predict(future)

        # Get future forecasts only
        future_forecast = forecast.tail(periods_ahead)

        forecasts = []
        for _, row in future_forecast.iterrows():
            forecasts.append(
                {
                    "timestamp": row["ds"].isoformat(),
                    "predicted": round(float(row["yhat"]), 4),
                    "lower_bound": round(float(row["yhat_lower"]), 4),
                    "upper_bound": round(float(row["yhat_upper"]), 4),
                }
            )

        # Calculate trend
        current_value = float(values_list[-1])
        final_forecast = forecasts[-1]["predicted"] if forecasts else current_value
        pct_change = (
            ((final_forecast - current_value) / current_value * 100)
            if current_value != 0
            else 0
        )

        result = {
            "ok": True,
            "metric": metric_name,
            "model": "prophet",
            "current_value": current_value,
            "forecasts": forecasts,
            "periods_ahead": periods_ahead,
            "trend": {
                "final_predicted": final_forecast,
                "change_percent": round(pct_change, 2),
                "direction": (
                    "increasing"
                    if pct_change > 2
                    else "decreasing" if pct_change < -2 else "stable"
                ),
            },
            "warning": _get_forecast_warning_prophet(
                current_value, forecasts, metric_name
            ),
        }

        if include_history:
            historical = forecast.head(len(values_list))
            result["historical_fit"] = [
                {
                    "timestamp": row["ds"].isoformat(),
                    "predicted": round(float(row["yhat"]), 4),
                }
                for _, row in historical.iterrows()
            ]

        logger.info(
            "prophet_forecast_completed", metric=metric_name, periods=periods_ahead
        )
        return json.dumps(result)

    except Exception as e:
        logger.error("prophet_forecast_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


def _get_forecast_warning_prophet(
    current: float, forecasts: list[dict], metric_name: str
) -> str | None:
    """Generate warning for Prophet forecast."""
    if not forecasts:
        return None

    final = forecasts[-1]["predicted"]
    upper = forecasts[-1]["upper_bound"]

    if final > current * 2:
        return f"Warning: {metric_name} is projected to double. Consider scaling or optimization."
    elif final < current * 0.5:
        return f"Warning: {metric_name} is projected to drop significantly."
    elif upper > current * 3:
        return "Warning: Upper bound shows potential for 3x increase."

    return None


@function_tool
def prophet_decompose(values: str, timestamps: str, metric_name: str = "metric") -> str:
    """
    Decompose a time series into trend, seasonality, and residuals using Prophet.

    Use cases:
    - Understand if metric behavior is driven by trend vs seasonality
    - Identify the magnitude of daily/weekly patterns
    - Separate noise from signal for clearer analysis

    Args:
        values: JSON array of metric values
        timestamps: JSON array of ISO timestamps
        metric_name: Name of the metric

    Returns:
        JSON with trend, daily seasonality, weekly seasonality, and residuals
    """
    if not _is_prophet_available():
        return json.dumps(
            {
                "ok": False,
                "error": "Prophet not installed. Install with: pip install prophet",
            }
        )

    try:
        import pandas as pd
        from prophet import Prophet

        values_list = json.loads(values)
        timestamps_list = json.loads(timestamps)

        if len(values_list) != len(timestamps_list):
            return json.dumps(
                {"ok": False, "error": "Values and timestamps must have same length"}
            )

        if len(values_list) < 24:  # Need at least a day of data for seasonality
            return json.dumps(
                {"ok": False, "error": "Need at least 24 data points for decomposition"}
            )

        df = pd.DataFrame(
            {
                "ds": pd.to_datetime(timestamps_list),
                "y": [float(v) for v in values_list],
            }
        )

        model = Prophet(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=False,
        )

        import logging

        logging.getLogger("prophet").setLevel(logging.WARNING)

        model.fit(df)
        forecast = model.predict(df)

        # Calculate residuals
        residuals = [
            float(values_list[i]) - float(forecast["yhat"].iloc[i])
            for i in range(len(values_list))
        ]

        # Get trend stats
        trend_values = forecast["trend"].tolist()
        trend_start = trend_values[0]
        trend_end = trend_values[-1]
        trend_change = (
            ((trend_end - trend_start) / trend_start * 100) if trend_start != 0 else 0
        )

        # Get seasonality magnitude
        daily_seasonality = []
        weekly_seasonality = []

        if "daily" in forecast.columns:
            daily_seasonality = forecast["daily"].tolist()
        if "weekly" in forecast.columns:
            weekly_seasonality = forecast["weekly"].tolist()

        daily_amplitude = (
            (max(daily_seasonality) - min(daily_seasonality))
            if daily_seasonality
            else 0
        )
        weekly_amplitude = (
            (max(weekly_seasonality) - min(weekly_seasonality))
            if weekly_seasonality
            else 0
        )

        # Variance decomposition (approximate)
        total_var = statistics.variance(values_list) if len(values_list) > 1 else 1
        residual_var = statistics.variance(residuals) if len(residuals) > 1 else 0
        explained_var = 1 - (residual_var / total_var) if total_var > 0 else 0

        result = {
            "ok": True,
            "metric": metric_name,
            "model": "prophet",
            "data_points": len(values_list),
            "trend": {
                "start": round(trend_start, 4),
                "end": round(trend_end, 4),
                "change_percent": round(trend_change, 2),
                "direction": (
                    "increasing"
                    if trend_change > 1
                    else "decreasing" if trend_change < -1 else "stable"
                ),
            },
            "seasonality": {
                "daily_amplitude": round(daily_amplitude, 4),
                "weekly_amplitude": round(weekly_amplitude, 4),
                "dominant": (
                    "daily"
                    if daily_amplitude > weekly_amplitude
                    else "weekly" if weekly_amplitude > 0 else "none"
                ),
            },
            "residuals": {
                "mean": round(statistics.mean(residuals), 4),
                "stdev": round(
                    statistics.stdev(residuals) if len(residuals) > 1 else 0, 4
                ),
            },
            "model_fit": {
                "variance_explained": round(explained_var, 4),
                "quality": (
                    "good"
                    if explained_var > 0.7
                    else "moderate" if explained_var > 0.4 else "poor"
                ),
            },
            "insight": _get_decomposition_insight(
                trend_change,
                daily_amplitude,
                weekly_amplitude,
                explained_var,
                metric_name,
            ),
        }

        logger.info("prophet_decomposition_completed", metric=metric_name)
        return json.dumps(result)

    except Exception as e:
        logger.error("prophet_decomposition_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


def _get_decomposition_insight(
    trend_pct: float, daily: float, weekly: float, explained: float, metric_name: str
) -> str:
    """Generate insight from decomposition."""
    parts = []

    if abs(trend_pct) > 10:
        direction = "increasing" if trend_pct > 0 else "decreasing"
        parts.append(
            f"{metric_name} has a strong {direction} trend ({trend_pct:.1f}%)."
        )

    if daily > 0 and daily > weekly:
        parts.append("Strong daily seasonality detected.")
    elif weekly > daily:
        parts.append("Strong weekly seasonality detected.")

    if explained > 0.7:
        parts.append(
            f"Model explains {explained*100:.0f}% of variance - predictions should be reliable."
        )
    elif explained < 0.4:
        parts.append(
            f"Model explains only {explained*100:.0f}% of variance - high unpredictability."
        )

    return (
        " ".join(parts)
        if parts
        else f"{metric_name} shows stable behavior with no strong patterns."
    )


# Register tools
register_tool("detect_anomalies", detect_anomalies)
register_tool("correlate_metrics", correlate_metrics)
register_tool("find_change_point", find_change_point)
register_tool("forecast_metric", forecast_metric)
register_tool("analyze_metric_distribution", analyze_metric_distribution)
register_tool("prophet_detect_anomalies", prophet_detect_anomalies)
register_tool("prophet_forecast", prophet_forecast)
register_tool("prophet_decompose", prophet_decompose)
