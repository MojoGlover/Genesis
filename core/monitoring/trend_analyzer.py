"""
GENESIS Trend Analyzer & Anomaly Detector

Analyzes time-series metrics to detect anomalies, trends, and predict potential issues.
Uses statistical methods (z-score, moving averages, IQR) without requiring ML libraries.

Key features:
- Anomaly detection using multiple algorithms
- Trend detection (increasing, decreasing, stable)
- Seasonal pattern recognition
- Predictive alerting (alert before threshold breach)
- Integration with AlertSystem and IncidentTracker

Integrates with:
- MetricsCollector: reads historical metric data
- AlertSystem: sends predictive alerts
- IncidentTracker: creates incidents for detected anomalies
- Message bus: broadcasts anomaly events
- Dashboard: API endpoints for trend visualization
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from core.messaging import Message, MessageType, get_message_bus

logger = logging.getLogger(__name__)


class TrendDirection(Enum):
    """Direction of a detected trend."""
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    VOLATILE = "volatile"


class AnomalyType(Enum):
    """Type of detected anomaly."""
    SPIKE = "spike"
    DROP = "drop"
    DRIFT = "drift"
    SEASONALITY_BREAK = "seasonality_break"
    THRESHOLD_PREDICTED = "threshold_predicted"


class AnomalySeverity(Enum):
    """Severity of detected anomaly."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Anomaly:
    """A detected anomaly in metric data."""
    anomaly_id: str
    metric_name: str
    agent: str
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    detected_at: datetime
    value: float
    expected_value: float
    deviation: float
    message: str
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "anomaly_id": self.anomaly_id,
            "metric_name": self.metric_name,
            "agent": self.agent,
            "anomaly_type": self.anomaly_type.value,
            "severity": self.severity.value,
            "detected_at": self.detected_at.isoformat(),
            "value": self.value,
            "expected_value": round(self.expected_value, 2),
            "deviation": round(self.deviation, 2),
            "message": self.message,
            "context": self.context,
        }


@dataclass
class TrendAnalysis:
    """Analysis of a metric's trend."""
    metric_name: str
    agent: str
    direction: TrendDirection
    slope: float
    confidence: float
    period_hours: float
    start_value: float
    end_value: float
    samples: int
    analyzed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "agent": self.agent,
            "direction": self.direction.value,
            "slope": round(self.slope, 4),
            "confidence": round(self.confidence, 2),
            "period_hours": self.period_hours,
            "start_value": round(self.start_value, 2),
            "end_value": round(self.end_value, 2),
            "samples": self.samples,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


@dataclass
class MetricBaseline:
    """Statistical baseline for a metric."""
    metric_name: str
    agent: str
    mean: float
    std_dev: float
    min_val: float
    max_val: float
    p25: float
    p50: float
    p75: float
    sample_count: int
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "agent": self.agent,
            "mean": round(self.mean, 2),
            "std_dev": round(self.std_dev, 2),
            "min": round(self.min_val, 2),
            "max": round(self.max_val, 2),
            "p25": round(self.p25, 2),
            "p50": round(self.p50, 2),
            "p75": round(self.p75, 2),
            "sample_count": self.sample_count,
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class TrendAnalyzerConfig:
    """Configuration for trend analysis."""
    analysis_interval_seconds: float = 60.0
    baseline_window_hours: float = 24.0
    trend_window_hours: float = 1.0
    z_score_threshold: float = 3.0
    iqr_multiplier: float = 1.5
    spike_threshold_percent: float = 50.0
    drift_threshold_percent: float = 20.0
    enable_predictive: bool = True
    prediction_horizon_minutes: float = 15.0
    threshold_buffer_percent: float = 10.0
    max_anomalies_history: int = 500
    max_baselines: int = 100
    min_samples_for_baseline: int = 30


class TrendAnalyzer:
    """Analyzes metrics for anomalies, trends, and predictions."""

    def __init__(self, config: Optional[TrendAnalyzerConfig] = None):
        self._config = config or TrendAnalyzerConfig()
        self._baselines: Dict[str, MetricBaseline] = {}
        self._anomalies: Deque[Anomaly] = deque(maxlen=self._config.max_anomalies_history)
        self._recent_values: Dict[str, Deque[Tuple[datetime, float]]] = {}
        self._lock = threading.RLock()
        self._running = False
        self._analysis_thread: Optional[threading.Thread] = None
        self._anomaly_counter = 0
        self._on_anomaly: List[Callable[[Anomaly], None]] = []
        self._thresholds: Dict[str, Dict[str, float]] = {
            "sys.cpu.percent": {"warning": 80, "critical": 95},
            "sys.mem.percent": {"warning": 80, "critical": 95},
            "sys.disk.percent": {"warning": 85, "critical": 95},
            "error_rate": {"warning": 0.1, "critical": 0.25},
        }

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        bus = get_message_bus()
        bus.subscribe(MessageType.STATUS_REPORT, self._handle_metrics)
        self._analysis_thread = threading.Thread(
            target=self._analysis_loop, daemon=True, name="trend-analyzer"
        )
        self._analysis_thread.start()
        logger.info("Trend analyzer started")

    def stop(self) -> None:
        self._running = False
        if self._analysis_thread:
            self._analysis_thread.join(timeout=5.0)
        logger.info("Trend analyzer stopped")

    def analyze_metric(
        self, metric_name: str, agent: str,
        values: Optional[List[Tuple[datetime, float]]] = None,
    ) -> List[Anomaly]:
        if values is None:
            values = self._fetch_metric_values(metric_name, agent)
        if len(values) < self._config.min_samples_for_baseline:
            return []
        anomalies = []
        key = f"{metric_name}:{agent}"
        baseline = self._calculate_baseline(metric_name, agent, values)
        with self._lock:
            self._baselines[key] = baseline
        recent = values[-50:] if len(values) > 50 else values
        anomalies.extend(self._detect_zscore_anomalies(metric_name, agent, recent, baseline))
        anomalies.extend(self._detect_iqr_anomalies(metric_name, agent, recent, baseline))
        anomalies.extend(self._detect_sudden_changes(metric_name, agent, recent))
        if self._config.enable_predictive:
            anomalies.extend(self._predict_threshold_breach(metric_name, agent, recent))
        for anomaly in anomalies:
            self._record_anomaly(anomaly)
        return anomalies

    def get_trend(self, metric_name: str, agent: str, hours: float = 1.0) -> Optional[TrendAnalysis]:
        values = self._fetch_metric_values(metric_name, agent, hours=hours)
        if len(values) < 10:
            return None
        timestamps = [(v[0] - values[0][0]).total_seconds() / 3600 for v in values]
        metric_values = [v[1] for v in values]
        slope, intercept, r_squared = self._linear_regression(timestamps, metric_values)
        if abs(slope) < 0.01:
            direction = TrendDirection.STABLE
        elif slope > 0:
            direction = TrendDirection.INCREASING
        else:
            direction = TrendDirection.DECREASING
        if r_squared < 0.3:
            std_dev = self._std_dev(metric_values)
            mean = sum(metric_values) / len(metric_values)
            cv = std_dev / mean if mean != 0 else 0
            if cv > 0.3:
                direction = TrendDirection.VOLATILE
        return TrendAnalysis(
            metric_name=metric_name, agent=agent, direction=direction,
            slope=slope, confidence=r_squared, period_hours=hours,
            start_value=metric_values[0], end_value=metric_values[-1], samples=len(values),
        )

    def get_baseline(self, metric_name: str, agent: str) -> Optional[MetricBaseline]:
        key = f"{metric_name}:{agent}"
        with self._lock:
            return self._baselines.get(key)

    def get_recent_anomalies(
        self, limit: int = 50, metric_name: Optional[str] = None,
        agent: Optional[str] = None, severity: Optional[AnomalySeverity] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            anomalies = list(self._anomalies)
        if metric_name:
            anomalies = [a for a in anomalies if a.metric_name == metric_name]
        if agent:
            anomalies = [a for a in anomalies if a.agent == agent]
        if severity:
            anomalies = [a for a in anomalies if a.severity == severity]
        anomalies.sort(key=lambda a: a.detected_at, reverse=True)
        return [a.to_dict() for a in anomalies[:limit]]

    def get_all_baselines(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {k: v.to_dict() for k, v in self._baselines.items()}

    def set_threshold(self, metric_name: str, warning: Optional[float] = None, critical: Optional[float] = None) -> None:
        if metric_name not in self._thresholds:
            self._thresholds[metric_name] = {}
        if warning is not None:
            self._thresholds[metric_name]["warning"] = warning
        if critical is not None:
            self._thresholds[metric_name]["critical"] = critical

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "baselines_count": len(self._baselines),
                "anomalies_count": len(self._anomalies),
                "thresholds": self._thresholds,
                "config": {
                    "z_score_threshold": self._config.z_score_threshold,
                    "analysis_interval_seconds": self._config.analysis_interval_seconds,
                    "enable_predictive": self._config.enable_predictive,
                },
            }

    def on_anomaly(self, callback: Callable[[Anomaly], None]) -> None:
        self._on_anomaly.append(callback)

    def _detect_zscore_anomalies(self, metric_name: str, agent: str,
        values: List[Tuple[datetime, float]], baseline: MetricBaseline) -> List[Anomaly]:
        anomalies = []
        if baseline.std_dev == 0:
            return anomalies
        for ts, value in values[-10:]:
            z_score = abs(value - baseline.mean) / baseline.std_dev
            if z_score >= self._config.z_score_threshold:
                severity = self._severity_from_zscore(z_score)
                anomaly_type = AnomalyType.SPIKE if value > baseline.mean else AnomalyType.DROP
                anomaly = Anomaly(
                    anomaly_id=self._generate_anomaly_id(), metric_name=metric_name,
                    agent=agent, anomaly_type=anomaly_type, severity=severity,
                    detected_at=ts, value=value, expected_value=baseline.mean,
                    deviation=z_score,
                    message=f"{metric_name} value {value:.2f} is {z_score:.1f} std devs from mean ({baseline.mean:.2f})",
                    context={"method": "z_score", "threshold": self._config.z_score_threshold},
                )
                anomalies.append(anomaly)
        return anomalies

    def _detect_iqr_anomalies(self, metric_name: str, agent: str,
        values: List[Tuple[datetime, float]], baseline: MetricBaseline) -> List[Anomaly]:
        anomalies = []
        iqr = baseline.p75 - baseline.p25
        if iqr == 0:
            return anomalies
        lower_bound = baseline.p25 - (self._config.iqr_multiplier * iqr)
        upper_bound = baseline.p75 + (self._config.iqr_multiplier * iqr)
        for ts, value in values[-10:]:
            if value < lower_bound or value > upper_bound:
                deviation = (value - baseline.p50) / iqr if iqr != 0 else 0
                severity = AnomalySeverity.MEDIUM if abs(deviation) < 3 else AnomalySeverity.HIGH
                anomaly = Anomaly(
                    anomaly_id=self._generate_anomaly_id(), metric_name=metric_name,
                    agent=agent, anomaly_type=AnomalyType.SPIKE if value > upper_bound else AnomalyType.DROP,
                    severity=severity, detected_at=ts, value=value, expected_value=baseline.p50,
                    deviation=deviation,
                    message=f"{metric_name} value {value:.2f} outside IQR bounds [{lower_bound:.2f}, {upper_bound:.2f}]",
                    context={"method": "iqr", "lower_bound": lower_bound, "upper_bound": upper_bound},
                )
                anomalies.append(anomaly)
        return anomalies

    def _detect_sudden_changes(self, metric_name: str, agent: str,
        values: List[Tuple[datetime, float]]) -> List[Anomaly]:
        anomalies = []
        if len(values) < 3:
            return anomalies
        window = min(5, len(values) - 1)
        for i in range(window, len(values)):
            recent_avg = sum(v[1] for v in values[i - window:i]) / window
            current = values[i][1]
            if recent_avg == 0:
                continue
            pct_change = ((current - recent_avg) / recent_avg) * 100
            if abs(pct_change) >= self._config.spike_threshold_percent:
                severity = AnomalySeverity.HIGH if abs(pct_change) > 100 else AnomalySeverity.MEDIUM
                anomaly_type = AnomalyType.SPIKE if pct_change > 0 else AnomalyType.DROP
                anomaly = Anomaly(
                    anomaly_id=self._generate_anomaly_id(), metric_name=metric_name,
                    agent=agent, anomaly_type=anomaly_type, severity=severity,
                    detected_at=values[i][0], value=current, expected_value=recent_avg,
                    deviation=pct_change,
                    message=f"{metric_name} changed {pct_change:+.1f}% from moving avg ({recent_avg:.2f} -> {current:.2f})",
                    context={"method": "sudden_change", "window": window},
                )
                anomalies.append(anomaly)
        return anomalies

    def _predict_threshold_breach(self, metric_name: str, agent: str,
        values: List[Tuple[datetime, float]]) -> List[Anomaly]:
        anomalies = []
        thresholds = self._thresholds.get(metric_name)
        if not thresholds or len(values) < 10:
            return anomalies
        timestamps = [(v[0] - values[0][0]).total_seconds() / 60 for v in values]
        metric_values = [v[1] for v in values]
        slope, intercept, r_squared = self._linear_regression(timestamps, metric_values)
        if r_squared < 0.5:
            return anomalies
        horizon = timestamps[-1] + self._config.prediction_horizon_minutes
        predicted_value = slope * horizon + intercept
        current_value = metric_values[-1]
        for level, threshold in thresholds.items():
            buffer = threshold * (self._config.threshold_buffer_percent / 100)
            if slope > 0 and predicted_value >= threshold - buffer:
                if current_value < threshold:
                    time_to_breach = (threshold - intercept) / slope if slope > 0 else float("inf")
                    minutes_to_breach = max(0, time_to_breach - timestamps[-1])
                    anomaly = Anomaly(
                        anomaly_id=self._generate_anomaly_id(), metric_name=metric_name,
                        agent=agent, anomaly_type=AnomalyType.THRESHOLD_PREDICTED,
                        severity=AnomalySeverity.HIGH if level == "critical" else AnomalySeverity.MEDIUM,
                        detected_at=datetime.now(), value=current_value, expected_value=threshold,
                        deviation=(predicted_value - threshold),
                        message=f"{metric_name} predicted to breach {level} threshold ({threshold}) in ~{minutes_to_breach:.0f} min",
                        context={
                            "method": "predictive", "threshold_level": level,
                            "threshold_value": threshold, "predicted_value": round(predicted_value, 2),
                            "minutes_to_breach": round(minutes_to_breach, 1), "confidence": round(r_squared, 2),
                        },
                    )
                    anomalies.append(anomaly)
        return anomalies

    def _calculate_baseline(self, metric_name: str, agent: str,
        values: List[Tuple[datetime, float]]) -> MetricBaseline:
        metric_values = sorted([v[1] for v in values])
        n = len(metric_values)
        mean = sum(metric_values) / n
        variance = sum((x - mean) ** 2 for x in metric_values) / n
        std_dev = math.sqrt(variance)
        return MetricBaseline(
            metric_name=metric_name, agent=agent, mean=mean, std_dev=std_dev,
            min_val=metric_values[0], max_val=metric_values[-1],
            p25=metric_values[int(n * 0.25)], p50=metric_values[int(n * 0.50)],
            p75=metric_values[int(n * 0.75)], sample_count=n,
        )

    def _severity_from_zscore(self, z_score: float) -> AnomalySeverity:
        if z_score >= 5:
            return AnomalySeverity.CRITICAL
        elif z_score >= 4:
            return AnomalySeverity.HIGH
        elif z_score >= 3:
            return AnomalySeverity.MEDIUM
        return AnomalySeverity.LOW

    def _linear_regression(self, x: List[float], y: List[float]) -> Tuple[float, float, float]:
        n = len(x)
        if n < 2:
            return 0.0, y[0] if y else 0.0, 0.0
        sum_x, sum_y = sum(x), sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_x2 = sum(xi ** 2 for xi in x)
        sum_y2 = sum(yi ** 2 for yi in y)
        denom = n * sum_x2 - sum_x ** 2
        if denom == 0:
            return 0.0, sum_y / n, 0.0
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        ss_tot = sum_y2 - (sum_y ** 2) / n
        ss_res = sum((y[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0
        return slope, intercept, max(0, min(1, r_squared))

    def _std_dev(self, values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return math.sqrt(variance)

    def _generate_anomaly_id(self) -> str:
        with self._lock:
            self._anomaly_counter += 1
            return f"ANM-{self._anomaly_counter:06d}"

    def _record_anomaly(self, anomaly: Anomaly) -> None:
        with self._lock:
            self._anomalies.append(anomaly)
        for callback in self._on_anomaly:
            try:
                callback(anomaly)
            except Exception as e:
                logger.error(f"Anomaly callback error: {e}")
        try:
            bus = get_message_bus()
            bus.publish(Message(
                type=MessageType.ALERT, sender="trend_analyzer",
                payload={"alert_type": "anomaly", "anomaly": anomaly.to_dict()},
            ))
        except Exception as e:
            logger.error(f"Failed to broadcast anomaly: {e}")

    def _fetch_metric_values(self, metric_name: str, agent: str,
        hours: Optional[float] = None) -> List[Tuple[datetime, float]]:
        try:
            from .metrics import get_metrics_collector
            collector = get_metrics_collector()
            hours = hours or self._config.baseline_window_hours
            series_list = collector.query(metric_name, agent, hours=hours)
            values = []
            for series in series_list:
                for point in series.data_points:
                    values.append((point.timestamp, point.value))
            values.sort(key=lambda x: x[0])
            return values
        except Exception as e:
            logger.error(f"Failed to fetch metrics for {metric_name}:{agent}: {e}")
            return []

    def _handle_metrics(self, message: Message) -> None:
        try:
            details = message.payload.get("details", {})
            agent = message.sender
            for category, metrics in details.items():
                if isinstance(metrics, dict):
                    for name, value in metrics.items():
                        if isinstance(value, (int, float)):
                            key = f"{category}.{name}:{agent}"
                            self._store_recent_value(key, value)
        except Exception as e:
            logger.error(f"Error handling metrics: {e}")

    def _store_recent_value(self, key: str, value: float) -> None:
        with self._lock:
            if key not in self._recent_values:
                self._recent_values[key] = deque(maxlen=100)
            self._recent_values[key].append((datetime.now(), value))

    def _analysis_loop(self) -> None:
        while self._running:
            time.sleep(self._config.analysis_interval_seconds)
            try:
                self._run_analysis_cycle()
            except Exception as e:
                logger.error(f"Analysis cycle error: {e}")

    def _run_analysis_cycle(self) -> None:
        try:
            from .metrics import get_metrics_collector
            collector = get_metrics_collector()
            current = collector.get_current()
            for metric_name, agents in current.items():
                for agent in agents:
                    try:
                        self.analyze_metric(metric_name, agent)
                    except Exception as e:
                        logger.error(f"Error analyzing {metric_name}:{agent}: {e}")
        except Exception as e:
            logger.error(f"Analysis cycle error: {e}")


_analyzer_instance: Optional[TrendAnalyzer] = None
_analyzer_lock = threading.Lock()


def get_trend_analyzer(config: Optional[TrendAnalyzerConfig] = None) -> TrendAnalyzer:
    global _analyzer_instance
    with _analyzer_lock:
        if _analyzer_instance is None:
            _analyzer_instance = TrendAnalyzer(config)
        return _analyzer_instance
