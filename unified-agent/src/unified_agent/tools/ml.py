"""Machine Learning and anomaly detection tools for metrics analysis."""

from typing import Any

import json
import logging
import os

from ..core.agent import function_tool
from . import register_tool


logger = logging.getLogger(__name__)


@function_tool
def detect_anomalies(
    metric_values: list[float],
    timestamps: list[str] | None = None,
    sensitivity: float = 3.0,
    method: str = "zscore",
) -> str:
    """
    Detect anomalies in a time series using statistical methods.

    Args:
        metric_values: List of metric values
        timestamps: Optional list of timestamps (ISO format)
        sensitivity: Sensitivity threshold (default 3.0 for z-score, means 3 standard deviations)
        method: Detection method ("zscore", "iqr", "mad")

    Returns:
        Dict with anomaly indices, scores, and statistics
    """
    try:
        import numpy as np

        if not metric_values or len(metric_values) < 3:
            return {
                "anomalies": [],
                "anomaly_count": 0,
                "message": "Insufficient data for anomaly detection (need at least 3 points)",
            }

        values = np.array(metric_values)

        if method == "zscore":
            # Z-score method (standard deviations from mean)
            mean = np.mean(values)
            std = np.std(values)

            if std == 0:
                return {
                    "anomalies": [],
                    "anomaly_count": 0,
                    "message": "No variance in data (all values identical)",
                }

            z_scores = np.abs((values - mean) / std)
            anomaly_indices = np.where(z_scores > sensitivity)[0].tolist()
            anomaly_scores = z_scores[anomaly_indices].tolist()

        elif method == "iqr":
            # Interquartile Range method
            q1 = np.percentile(values, 25)
            q3 = np.percentile(values, 75)
            iqr = q3 - q1

            lower_bound = q1 - (sensitivity * iqr)
            upper_bound = q3 + (sensitivity * iqr)

            anomaly_mask = (values < lower_bound) | (values > upper_bound)
            anomaly_indices = np.where(anomaly_mask)[0].tolist()
            anomaly_scores = np.abs(
                values[anomaly_indices] - np.median(values)
            ).tolist()

        elif method == "mad":
            # Median Absolute Deviation
            median = np.median(values)
            mad = np.median(np.abs(values - median))

            if mad == 0:
                return {
                    "anomalies": [],
                    "anomaly_count": 0,
                    "message": "MAD is zero (data has no spread)",
                }

            modified_z_scores = 0.6745 * (values - median) / mad
            anomaly_indices = np.where(np.abs(modified_z_scores) > sensitivity)[
                0
            ].tolist()
            anomaly_scores = np.abs(modified_z_scores[anomaly_indices]).tolist()

        else:
            raise ValueError(f"Unknown method: {method}")

        # Build anomaly list
        anomalies = []
        for idx, score in zip(anomaly_indices, anomaly_scores):
            anomaly = {
                "index": int(idx),
                "value": float(values[idx]),
                "score": float(score),
            }
            if timestamps and idx < len(timestamps):
                anomaly["timestamp"] = timestamps[idx]
            anomalies.append(anomaly)

        logger.info("anomalies_detected", count=len(anomalies), method=method)

        return {
            "method": method,
            "sensitivity": sensitivity,
            "data_points": len(metric_values),
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
            "statistics": {
                "mean": float(np.mean(values)),
                "median": float(np.median(values)),
                "std": float(np.std(values)),
                "min": float(np.min(values)),
                "max": float(np.max(values)),
            },
        }

    except ImportError:
        return json.dumps({"ok": False, "error": "Tool execution error"})
            "detect_anomalies", "numpy not installed. Install with: poetry add numpy"
        )
    except Exception as e:
        logger.error("anomaly_detection_failed", error=str(e))
        return json.dumps({"ok": False, "error": "detect_anomalies"})


@function_tool
def calculate_baseline(
    metric_values: list[float],
    timestamps: list[str] | None = None,
    percentiles: list[int] | None = None,
) -> str:
    """
    Calculate statistical baseline for a metric.

    Use this to understand normal behavior and set appropriate alert thresholds.

    Args:
        metric_values: List of metric values
        timestamps: Optional timestamps
        percentiles: Percentiles to calculate (default [50, 75, 90, 95, 99])

    Returns:
        Dict with statistical baseline including mean, median, percentiles, and recommended thresholds
    """
    try:
        import numpy as np

        if not metric_values:
            return {"error": "No data provided"}

        values = np.array(metric_values)
        percentiles = percentiles or [50, 75, 90, 95, 99]

        # Calculate statistics
        stats = {
            "count": len(values),
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "std": float(np.std(values)),
            "min": float(np.min(values)),
            "max": float(np.max(values)),
        }

        # Calculate percentiles
        pctl_values = {}
        for p in percentiles:
            pctl_values[f"p{p}"] = float(np.percentile(values, p))

        stats["percentiles"] = pctl_values

        # Recommend alert thresholds based on distribution
        # Use P95 + 2*std as a reasonable alert threshold
        recommended_threshold = stats["percentiles"]["p95"] + (2 * stats["std"])

        # Also calculate "definitely bad" threshold (P99 + 3*std)
        critical_threshold = stats["percentiles"]["p99"] + (3 * stats["std"])

        logger.info("baseline_calculated", points=len(values), mean=stats["mean"])

        return {
            "statistics": stats,
            "recommended_thresholds": {
                "warning": float(recommended_threshold),
                "critical": float(critical_threshold),
                "explanation": f"Warning at P95 + 2σ ({recommended_threshold:.2f}), Critical at P99 + 3σ ({critical_threshold:.2f})",
            },
            "interpretation": {
                "typical_range": f"{stats['percentiles']['p50']:.2f} - {stats['percentiles']['p95']:.2f}",
                "high_variance": stats["std"] > (0.5 * stats["mean"]),
            },
        }

    except ImportError:
        return json.dumps({"ok": False, "error": "Tool execution error"})
            "calculate_baseline", "numpy not installed. Install with: poetry add numpy"
        )
    except Exception as e:
        logger.error("baseline_calculation_failed", error=str(e))
        return json.dumps({"ok": False, "error": "calculate_baseline"})


@function_tool
def forecast_metric(
    metric_values: list[float],
    timestamps: list[str] | None = None,
    forecast_points: int = 10,
    method: str = "linear",
) -> str:
    """
    Forecast future metric values using time series analysis.

    Use this to predict if a metric will cross a threshold in the near future.

    Args:
        metric_values: Historical metric values
        timestamps: Optional timestamps
        forecast_points: Number of future points to forecast
        method: Forecasting method ("linear", "moving_average")

    Returns:
        Dict with forecasted values and trend analysis
    """
    try:
        import numpy as np

        if not metric_values or len(metric_values) < 2:
            return {
                "error": "Insufficient data for forecasting (need at least 2 points)"
            }

        values = np.array(metric_values)

        if method == "linear":
            # Simple linear regression
            x = np.arange(len(values))
            coeffs = np.polyfit(x, values, 1)
            slope, intercept = coeffs

            # Forecast future points
            future_x = np.arange(len(values), len(values) + forecast_points)
            forecasted = slope * future_x + intercept

            trend = "increasing" if slope > 0 else "decreasing" if slope < 0 else "flat"

        elif method == "moving_average":
            # Simple moving average
            window = min(5, len(values))
            ma = np.convolve(values, np.ones(window) / window, mode="valid")
            last_ma = ma[-1]

            # Forecast as continuation of last moving average
            forecasted = np.full(forecast_points, last_ma)
            trend = "stable"

        else:
            raise ValueError(f"Unknown method: {method}")

        logger.info(
            "metric_forecasted",
            points=len(values),
            forecast=forecast_points,
            method=method,
        )

        return {
            "method": method,
            "historical_points": len(metric_values),
            "forecast_points": forecast_points,
            "trend": trend,
            "slope": float(slope) if method == "linear" else None,
            "forecasted_values": forecasted.tolist(),
            "current_value": float(values[-1]),
            "forecasted_end_value": float(forecasted[-1]),
            "change_percent": (
                float(((forecasted[-1] - values[-1]) / values[-1]) * 100)
                if values[-1] != 0
                else 0
            ),
        }

    except ImportError:
        return json.dumps({"ok": False, "error": "Tool execution error"})
            "forecast_metric", "numpy not installed. Install with: poetry add numpy"
        )
    except Exception as e:
        logger.error("forecast_failed", error=str(e))
        return json.dumps({"ok": False, "error": "forecast_metric"})


# List of all ML tools for registration
ML_TOOLS = [
    detect_anomalies,
    calculate_baseline,
    forecast_metric,
]


# Register tools
register_tool("detect_anomalies", detect_anomalies)
register_tool("calculate_baseline", calculate_baseline)
register_tool("forecast_metric", forecast_metric)
