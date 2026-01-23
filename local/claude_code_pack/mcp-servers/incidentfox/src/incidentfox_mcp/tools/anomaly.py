"""Anomaly detection and metrics analysis tools.

Provides statistical analysis tools:
- detect_anomalies: Z-score based anomaly detection
- correlate_metrics: Find metric correlations
- find_change_point: Detect when behavior changed
"""

import json
import statistics
from typing import Any

from mcp.server.fastmcp import FastMCP


def _z_score(value: float, mean: float, std: float) -> float:
    """Calculate Z-score for a value."""
    if std == 0:
        return 0.0
    return (value - mean) / std


def register_tools(mcp: FastMCP):
    """Register anomaly detection tools with the MCP server."""

    @mcp.tool()
    def detect_anomalies(
        values: str,
        threshold: float = 2.0,
        labels: str | None = None,
    ) -> str:
        """Detect anomalies in a list of values using Z-score method.

        Values more than `threshold` standard deviations from the mean are flagged.

        Args:
            values: JSON array of numeric values (e.g., "[1.2, 1.3, 5.0, 1.1, 1.4]")
            threshold: Z-score threshold for anomaly detection (default: 2.0)
            labels: Optional JSON array of labels for each value (e.g., '["t1", "t2", "t3"]')

        Returns:
            JSON with statistics and detected anomalies
        """
        try:
            data = json.loads(values)
            if not data:
                return json.dumps({"error": "Empty data array"})

            label_list = json.loads(labels) if labels else list(range(len(data)))

            # Calculate statistics
            mean = statistics.mean(data)
            std = statistics.stdev(data) if len(data) > 1 else 0

            # Detect anomalies
            anomalies = []
            for i, value in enumerate(data):
                z = _z_score(value, mean, std)
                if abs(z) > threshold:
                    anomalies.append(
                        {
                            "index": i,
                            "label": label_list[i] if i < len(label_list) else i,
                            "value": value,
                            "z_score": round(z, 2),
                            "deviation": "high" if z > 0 else "low",
                        }
                    )

            return json.dumps(
                {
                    "statistics": {
                        "mean": round(mean, 4),
                        "std": round(std, 4),
                        "min": min(data),
                        "max": max(data),
                        "count": len(data),
                    },
                    "threshold": threshold,
                    "anomaly_count": len(anomalies),
                    "anomalies": anomalies,
                },
                indent=2,
            )

        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def correlate_metrics(
        metric_a: str,
        metric_b: str,
        labels_a: str | None = None,
        labels_b: str | None = None,
    ) -> str:
        """Calculate correlation between two metrics.

        Useful for finding if two metrics move together (e.g., CPU and latency).

        Args:
            metric_a: JSON array of numeric values for first metric
            metric_b: JSON array of numeric values for second metric
            labels_a: Optional name for first metric (default: "metric_a")
            labels_b: Optional name for second metric (default: "metric_b")

        Returns:
            JSON with Pearson correlation coefficient and interpretation
        """
        try:
            data_a = json.loads(metric_a)
            data_b = json.loads(metric_b)

            name_a = labels_a or "metric_a"
            name_b = labels_b or "metric_b"

            if len(data_a) != len(data_b):
                return json.dumps(
                    {
                        "error": f"Metric arrays must have same length ({len(data_a)} vs {len(data_b)})"
                    }
                )

            if len(data_a) < 2:
                return json.dumps({"error": "Need at least 2 data points"})

            # Calculate Pearson correlation
            n = len(data_a)
            mean_a = statistics.mean(data_a)
            mean_b = statistics.mean(data_b)

            covariance = (
                sum((data_a[i] - mean_a) * (data_b[i] - mean_b) for i in range(n)) / n
            )

            std_a = statistics.stdev(data_a)
            std_b = statistics.stdev(data_b)

            if std_a == 0 or std_b == 0:
                correlation = 0.0
            else:
                correlation = covariance / (std_a * std_b)

            # Interpret correlation
            abs_corr = abs(correlation)
            if abs_corr >= 0.8:
                strength = "strong"
            elif abs_corr >= 0.5:
                strength = "moderate"
            elif abs_corr >= 0.3:
                strength = "weak"
            else:
                strength = "negligible"

            direction = "positive" if correlation >= 0 else "negative"

            return json.dumps(
                {
                    "metrics": {
                        name_a: {"mean": round(mean_a, 4), "std": round(std_a, 4)},
                        name_b: {"mean": round(mean_b, 4), "std": round(std_b, 4)},
                    },
                    "correlation": round(correlation, 4),
                    "interpretation": f"{strength} {direction} correlation",
                    "data_points": n,
                },
                indent=2,
            )

        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def find_change_point(
        values: str,
        labels: str | None = None,
        window_size: int = 5,
    ) -> str:
        """Detect change points in a time series.

        Finds where the behavior of a metric significantly changed.
        Useful for identifying when an incident started.

        Args:
            values: JSON array of numeric values in chronological order
            labels: Optional JSON array of timestamps/labels for each value
            window_size: Window size for comparison (default: 5)

        Returns:
            JSON with detected change points and their magnitude
        """
        try:
            data = json.loads(values)
            label_list = json.loads(labels) if labels else list(range(len(data)))

            if len(data) < window_size * 2:
                return json.dumps(
                    {
                        "error": f"Need at least {window_size * 2} data points for window_size={window_size}"
                    }
                )

            change_points = []

            # Sliding window comparison
            for i in range(window_size, len(data) - window_size + 1):
                before = data[i - window_size : i]
                after = data[i : i + window_size]

                mean_before = statistics.mean(before)
                mean_after = statistics.mean(after)
                std_before = statistics.stdev(before) if len(before) > 1 else 0.001

                # Calculate change magnitude
                change = mean_after - mean_before
                change_z = change / std_before if std_before > 0 else 0

                # Significant change if Z > 2
                if abs(change_z) > 2:
                    change_points.append(
                        {
                            "index": i,
                            "label": label_list[i] if i < len(label_list) else i,
                            "mean_before": round(mean_before, 4),
                            "mean_after": round(mean_after, 4),
                            "change": round(change, 4),
                            "change_percent": (
                                round((change / mean_before) * 100, 2)
                                if mean_before != 0
                                else None
                            ),
                            "direction": "increase" if change > 0 else "decrease",
                        }
                    )

            # Find the most significant change point
            most_significant = None
            if change_points:
                most_significant = max(
                    change_points, key=lambda x: abs(x.get("change_percent", 0) or 0)
                )

            return json.dumps(
                {
                    "data_points": len(data),
                    "window_size": window_size,
                    "change_point_count": len(change_points),
                    "most_significant": most_significant,
                    "all_change_points": change_points,
                },
                indent=2,
            )

        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            return json.dumps({"error": str(e)})
