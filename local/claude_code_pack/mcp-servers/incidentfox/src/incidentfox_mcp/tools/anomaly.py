"""Anomaly detection and metrics analysis tools.

Provides statistical analysis tools:
- detect_anomalies: Z-score based anomaly detection
- correlate_metrics: Find metric correlations
- find_change_point: Detect when behavior changed
- forecast_metric: Linear regression forecasting
- analyze_metric_distribution: Distribution analysis with percentiles/SLO insights
- prophet_detect_anomalies: Prophet-based seasonal anomaly detection
- prophet_forecast: Prophet forecasting with uncertainty
- prophet_decompose: Trend/seasonality decomposition
"""

import json
import statistics
from typing import Any

from mcp.server.fastmcp import FastMCP


def _is_prophet_available() -> bool:
    """Check if Prophet is installed."""
    try:
        from prophet import Prophet

        return True
    except ImportError:
        return False


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

    @mcp.tool()
    def forecast_metric(
        values: str,
        periods_ahead: int = 5,
        metric_name: str = "metric",
    ) -> str:
        """Forecast future metric values using linear regression.

        Provides quick linear extrapolation for capacity planning and trend prediction.
        For seasonality-aware forecasting, use prophet_forecast instead.

        Use cases:
        - Predict when a resource will be exhausted
        - Estimate future load based on trends
        - Project error rates

        Args:
            values: JSON array of historical values (e.g., "[1.2, 1.5, 1.8, 2.1, 2.4]")
            periods_ahead: Number of future periods to forecast (default: 5)
            metric_name: Name of the metric for reporting

        Returns:
            JSON with forecasted values and confidence bounds
        """
        try:
            data = [float(v) for v in json.loads(values)]

            if len(data) < 5:
                return json.dumps(
                    {"error": "Need at least 5 data points for forecasting"}
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

            # Generate warning
            warning = None
            if final_forecast > data[-1] * 2:
                warning = f"Warning: {metric_name} is projected to double. Consider scaling or optimization."
            elif final_forecast < data[-1] * 0.5:
                warning = f"Warning: {metric_name} is projected to drop significantly. Verify this is expected."
            elif final_forecast < 0:
                warning = (
                    "Warning: Forecast shows negative values which may be unrealistic."
                )

            return json.dumps(
                {
                    "metric": metric_name,
                    "current_value": data[-1],
                    "forecasts": forecasts,
                    "trend": {
                        "slope_per_period": round(slope, 4),
                        "forecast_change_percent": round(pct_change, 2),
                        "direction": (
                            "increasing"
                            if pct_change > 2
                            else "decreasing" if pct_change < -2 else "stable"
                        ),
                    },
                    "confidence": "linear_extrapolation",
                    "warning": warning,
                },
                indent=2,
            )

        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def analyze_metric_distribution(
        values: str,
        metric_name: str = "metric",
    ) -> str:
        """Analyze the distribution of metric values for deeper insights.

        Calculates percentiles, identifies distribution shape, and provides SLO insights.

        Use cases:
        - Understand if latency is normally distributed or has long tail
        - Identify bimodal distributions (two different behaviors)
        - Calculate percentiles for SLO analysis (p50, p90, p95, p99)

        Args:
            values: JSON array of numeric values
            metric_name: Name of the metric

        Returns:
            JSON with distribution analysis, percentiles, and SLO insights
        """
        try:
            data = [float(v) for v in json.loads(values)]

            if len(data) < 10:
                return json.dumps(
                    {"error": "Need at least 10 data points for distribution analysis"}
                )

            sorted_data = sorted(data)
            n = len(data)

            # Calculate percentiles
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
            potential_bimodal = abs(mean - p50) > stdev * 0.5

            # Long tail analysis
            p99_to_p50_ratio = p99 / p50 if p50 > 0 else 0
            has_long_tail = p99_to_p50_ratio > 3

            # SLO insight
            p95_vs_p50 = p95 / p50 if p50 > 0 else 1
            p99_vs_p95 = p99 / p95 if p95 > 0 else 1

            if p99_vs_p95 > 2:
                slo_insight = f"p99 is {p99_vs_p95:.1f}x higher than p95, indicating occasional extreme outliers. Consider investigating these edge cases."
            elif p95_vs_p50 > 2:
                slo_insight = f"p95 is {p95_vs_p50:.1f}x higher than p50, showing significant variance. The long tail may impact user experience."
            else:
                slo_insight = (
                    f"Distribution is relatively tight. p95={p95:.2f}, p99={p99:.2f}."
                )

            return json.dumps(
                {
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
                    "slo_insight": slo_insight,
                },
                indent=2,
            )

        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def prophet_detect_anomalies(
        values: str,
        timestamps: str,
        metric_name: str = "metric",
        interval_width: float = 0.95,
        seasonality_mode: str = "additive",
    ) -> str:
        """Detect anomalies using Facebook Prophet with seasonality awareness.

        Prophet excels at detecting anomalies that account for daily/weekly patterns,
        handling missing data gracefully, and providing uncertainty intervals.

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
            JSON with anomalies, trend, seasonality components, and severity
        """
        if not _is_prophet_available():
            return json.dumps(
                {
                    "error": "Prophet not installed. Install with: pip install prophet",
                    "fallback": "Use detect_anomalies() for basic statistical detection",
                }
            )

        try:
            import logging

            import pandas as pd
            from prophet import Prophet

            # Parse inputs
            values_list = json.loads(values)
            timestamps_list = json.loads(timestamps)

            if len(values_list) != len(timestamps_list):
                return json.dumps(
                    {
                        "error": f"Values ({len(values_list)}) and timestamps ({len(timestamps_list)}) must have same length"
                    }
                )

            if len(values_list) < 10:
                return json.dumps({"error": "Need at least 10 data points for Prophet"})

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
                yearly_seasonality=False,
            )

            # Suppress Prophet's verbose output
            logging.getLogger("prophet").setLevel(logging.WARNING)
            logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

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
                ((trend_end - trend_start) / trend_start * 100)
                if trend_start != 0
                else 0
            )

            # Generate insight
            if severity == "none":
                insight = f"No anomalies detected in {metric_name}. Values are within expected seasonal patterns."
            else:
                above = sum(1 for a in anomalies if a.get("direction") == "above")
                below = len(anomalies) - above
                if above > below:
                    insight = f"Detected {len(anomalies)} anomalies, mostly ABOVE expected ({above} high, {below} low)."
                elif below > above:
                    insight = f"Detected {len(anomalies)} anomalies, mostly BELOW expected ({below} low, {above} high)."
                else:
                    insight = f"Detected {len(anomalies)} anomalies (mixed directions)."

            if abs(trend_change_pct) > 5:
                direction = "increasing" if trend_change_pct > 0 else "decreasing"
                insight += (
                    f" Overall trend is {direction} by {abs(trend_change_pct):.1f}%."
                )

            return json.dumps(
                {
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
                    "insight": insight,
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def prophet_forecast(
        values: str,
        timestamps: str,
        periods_ahead: int = 10,
        metric_name: str = "metric",
        include_history: bool = False,
    ) -> str:
        """Forecast future values using Facebook Prophet with uncertainty bounds.

        Prophet provides seasonality-aware forecasting with uncertainty intervals
        that widen over time, plus trend and seasonality decomposition.

        Use cases:
        - Predict capacity needs (when will disk fill up?)
        - Forecast traffic for capacity planning
        - Predict when SLO will be breached

        Args:
            values: JSON array of metric values
            timestamps: JSON array of ISO timestamps
            periods_ahead: Number of future periods to forecast (default: 10)
            metric_name: Name of the metric
            include_history: Include historical fit in response (default: False)

        Returns:
            JSON with forecast, uncertainty bounds, and trend analysis
        """
        if not _is_prophet_available():
            return json.dumps(
                {
                    "error": "Prophet not installed. Install with: pip install prophet",
                    "fallback": "Use forecast_metric() for basic linear forecasting",
                }
            )

        try:
            import logging

            import pandas as pd
            from prophet import Prophet

            values_list = json.loads(values)
            timestamps_list = json.loads(timestamps)

            if len(values_list) != len(timestamps_list):
                return json.dumps(
                    {"error": "Values and timestamps must have same length"}
                )

            if len(values_list) < 10:
                return json.dumps({"error": "Need at least 10 data points"})

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
                interval_width=0.80,
                daily_seasonality=True,
                weekly_seasonality=True,
            )

            logging.getLogger("prophet").setLevel(logging.WARNING)
            logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

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

            # Generate warning
            upper = forecasts[-1]["upper_bound"] if forecasts else current_value
            warning = None
            if final_forecast > current_value * 2:
                warning = f"Warning: {metric_name} is projected to double. Consider scaling or optimization."
            elif final_forecast < current_value * 0.5:
                warning = f"Warning: {metric_name} is projected to drop significantly."
            elif upper > current_value * 3:
                warning = "Warning: Upper bound shows potential for 3x increase."

            result = {
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
                "warning": warning,
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

            return json.dumps(result, indent=2)

        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def prophet_decompose(
        values: str,
        timestamps: str,
        metric_name: str = "metric",
    ) -> str:
        """Decompose a time series into trend, seasonality, and residuals using Prophet.

        Separates the signal into components to understand what drives metric behavior.

        Use cases:
        - Understand if metric behavior is driven by trend vs seasonality
        - Identify the magnitude of daily/weekly patterns
        - Separate noise from signal for clearer analysis

        Args:
            values: JSON array of metric values
            timestamps: JSON array of ISO timestamps
            metric_name: Name of the metric

        Returns:
            JSON with trend, daily/weekly seasonality, residuals, and model fit quality
        """
        if not _is_prophet_available():
            return json.dumps(
                {"error": "Prophet not installed. Install with: pip install prophet"}
            )

        try:
            import logging

            import pandas as pd
            from prophet import Prophet

            values_list = json.loads(values)
            timestamps_list = json.loads(timestamps)

            if len(values_list) != len(timestamps_list):
                return json.dumps(
                    {"error": "Values and timestamps must have same length"}
                )

            if len(values_list) < 24:
                return json.dumps(
                    {"error": "Need at least 24 data points for decomposition"}
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

            logging.getLogger("prophet").setLevel(logging.WARNING)
            logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

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
                ((trend_end - trend_start) / trend_start * 100)
                if trend_start != 0
                else 0
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

            # Generate insight
            parts = []
            if abs(trend_change) > 10:
                direction = "increasing" if trend_change > 0 else "decreasing"
                parts.append(
                    f"{metric_name} has a strong {direction} trend ({trend_change:.1f}%)."
                )

            if daily_amplitude > 0 and daily_amplitude > weekly_amplitude:
                parts.append("Strong daily seasonality detected.")
            elif weekly_amplitude > daily_amplitude:
                parts.append("Strong weekly seasonality detected.")

            if explained_var > 0.7:
                parts.append(
                    f"Model explains {explained_var * 100:.0f}% of variance - predictions should be reliable."
                )
            elif explained_var < 0.4:
                parts.append(
                    f"Model explains only {explained_var * 100:.0f}% of variance - high unpredictability."
                )

            insight = (
                " ".join(parts)
                if parts
                else f"{metric_name} shows stable behavior with no strong patterns."
            )

            return json.dumps(
                {
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
                    "insight": insight,
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e)})
