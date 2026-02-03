"""
GENESIS Metrics Collector

Time-series metrics storage for historical trending and analysis.
Uses SQLite for persistence with automatic rollup for efficient storage.

Features:
- Per-agent metric tracking (CPU, memory, latency, throughput)
- Automatic rollup (1m -> 5m -> 1h -> 1d)
- Query API for dashboards and analysis
- Prometheus-compatible export
"""

from __future__ import annotations
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics that can be collected."""
    GAUGE = "gauge"           # Point-in-time value (e.g., queue depth)
    COUNTER = "counter"       # Monotonically increasing (e.g., request count)
    HISTOGRAM = "histogram"   # Distribution (e.g., latency)


class Aggregation(Enum):
    """Aggregation methods for rollup."""
    AVG = "avg"
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
    LAST = "last"


@dataclass
class MetricPoint:
    """A single metric data point."""
    name: str
    agent: str
    value: float
    timestamp: datetime
    metric_type: MetricType = MetricType.GAUGE
    labels: Dict[str, str] = None

    def __post_init__(self):
        if self.labels is None:
            self.labels = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "agent": self.agent,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "type": self.metric_type.value,
            "labels": self.labels,
        }


@dataclass
class MetricSeries:
    """A time series of metric points."""
    name: str
    agent: str
    points: List[Tuple[datetime, float]]
    aggregation: Aggregation = Aggregation.AVG

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "agent": self.agent,
            "aggregation": self.aggregation.value,
            "points": [(ts.isoformat(), val) for ts, val in self.points],
        }


class MetricsCollector:
    """
    Time-series metrics collector with SQLite storage.

    Usage:
        collector = get_metrics_collector()
        
        # Record a metric
        collector.record("cpu_percent", "agent_1", 45.2)
        collector.record("requests_total", "api", 1523, metric_type=MetricType.COUNTER)
        
        # Query metrics
        series = collector.query("cpu_percent", "agent_1", hours=24)
        
        # Get current values
        current = collector.get_current("agent_1")
    """

    ROLLUP_INTERVALS = [
        ("raw", 60, 3600),
        ("1m", 300, 86400),
        ("5m", 3600, 604800),
        ("1h", 86400, 2592000),
    ]

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize the metrics collector."""
        if db_path is None:
            db_path = Path.home() / ".genesis" / "metrics.db"
        
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._running = False
        self._rollup_thread: Optional[threading.Thread] = None
        
        self._buffer: List[MetricPoint] = []
        self._buffer_lock = threading.Lock()
        self._max_buffer = 100
        
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS metrics_raw (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    value REAL NOT NULL,
                    timestamp DATETIME NOT NULL,
                    metric_type TEXT DEFAULT 'gauge',
                    labels TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_raw_agent_ts ON metrics_raw(agent, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_raw_name_ts ON metrics_raw(name, timestamp DESC);
                
                CREATE TABLE IF NOT EXISTS metrics_1m (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    avg_value REAL,
                    min_value REAL,
                    max_value REAL,
                    sum_value REAL,
                    count INTEGER,
                    bucket_start DATETIME NOT NULL,
                    UNIQUE(name, agent, bucket_start)
                );
                CREATE INDEX IF NOT EXISTS idx_1m_agent_ts ON metrics_1m(agent, bucket_start DESC);
                
                CREATE TABLE IF NOT EXISTS metrics_5m (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    avg_value REAL,
                    min_value REAL,
                    max_value REAL,
                    sum_value REAL,
                    count INTEGER,
                    bucket_start DATETIME NOT NULL,
                    UNIQUE(name, agent, bucket_start)
                );
                CREATE INDEX IF NOT EXISTS idx_5m_agent_ts ON metrics_5m(agent, bucket_start DESC);
                
                CREATE TABLE IF NOT EXISTS metrics_1h (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    avg_value REAL,
                    min_value REAL,
                    max_value REAL,
                    sum_value REAL,
                    count INTEGER,
                    bucket_start DATETIME NOT NULL,
                    UNIQUE(name, agent, bucket_start)
                );
                CREATE INDEX IF NOT EXISTS idx_1h_agent_ts ON metrics_1h(agent, bucket_start DESC);
                
                CREATE TABLE IF NOT EXISTS metrics_current (
                    name TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    value REAL NOT NULL,
                    timestamp DATETIME NOT NULL,
                    metric_type TEXT DEFAULT 'gauge',
                    PRIMARY KEY (name, agent)
                );
            """)

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a database connection."""
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def start(self) -> None:
        """Start the metrics collector background tasks."""
        if self._running:
            return
        
        self._running = True
        self._rollup_thread = threading.Thread(target=self._rollup_loop, daemon=True)
        self._rollup_thread.start()
        logger.info("Metrics collector started")

    def stop(self) -> None:
        """Stop the metrics collector."""
        self._running = False
        self._flush_buffer()
        if self._rollup_thread:
            self._rollup_thread.join(timeout=2.0)
        logger.info("Metrics collector stopped")

    def record(
        self,
        name: str,
        agent: str,
        value: float,
        metric_type: MetricType = MetricType.GAUGE,
        labels: Optional[Dict[str, str]] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Record a metric value."""
        point = MetricPoint(
            name=name,
            agent=agent,
            value=value,
            timestamp=timestamp or datetime.now(),
            metric_type=metric_type,
            labels=labels or {},
        )

        with self._buffer_lock:
            self._buffer.append(point)
            if len(self._buffer) >= self._max_buffer:
                self._flush_buffer()

    def _flush_buffer(self) -> None:
        """Flush buffered metrics to database."""
        with self._buffer_lock:
            if not self._buffer:
                return
            
            points = self._buffer.copy()
            self._buffer.clear()

        try:
            with self._get_connection() as conn:
                conn.executemany(
                    """INSERT INTO metrics_raw (name, agent, value, timestamp, metric_type, labels)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        (p.name, p.agent, p.value, p.timestamp.isoformat(),
                         p.metric_type.value, str(p.labels))
                        for p in points
                    ]
                )

                for p in points:
                    conn.execute(
                        """INSERT OR REPLACE INTO metrics_current (name, agent, value, timestamp, metric_type)
                           VALUES (?, ?, ?, ?, ?)""",
                        (p.name, p.agent, p.value, p.timestamp.isoformat(), p.metric_type.value)
                    )

        except Exception as e:
            logger.error(f"Failed to flush metrics: {e}")

    def query(
        self,
        name: str,
        agent: Optional[str] = None,
        hours: float = 1.0,
        aggregation: Aggregation = Aggregation.AVG,
        resolution: str = "auto",
    ) -> List[MetricSeries]:
        """Query metric time series."""
        self._flush_buffer()

        if resolution == "auto":
            if hours <= 1:
                resolution = "raw"
            elif hours <= 6:
                resolution = "1m"
            elif hours <= 48:
                resolution = "5m"
            else:
                resolution = "1h"

        start_time = datetime.now() - timedelta(hours=hours)
        table = f"metrics_{resolution}" if resolution != "raw" else "metrics_raw"
        
        if resolution == "raw":
            value_col = "value"
            ts_col = "timestamp"
        else:
            value_col = f"{aggregation.value}_value" if aggregation != Aggregation.LAST else "avg_value"
            ts_col = "bucket_start"

        results = []
        with self._get_connection() as conn:
            if agent:
                cursor = conn.execute(
                    f"""SELECT agent, {ts_col} as ts, {value_col} as val
                        FROM {table}
                        WHERE name = ? AND agent = ? AND {ts_col} >= ?
                        ORDER BY {ts_col}""",
                    (name, agent, start_time.isoformat())
                )
            else:
                cursor = conn.execute(
                    f"""SELECT agent, {ts_col} as ts, {value_col} as val
                        FROM {table}
                        WHERE name = ? AND {ts_col} >= ?
                        ORDER BY agent, {ts_col}""",
                    (name, start_time.isoformat())
                )

            agent_points: Dict[str, List[Tuple[datetime, float]]] = {}
            for row in cursor:
                ag = row["agent"]
                if ag not in agent_points:
                    agent_points[ag] = []
                agent_points[ag].append((
                    datetime.fromisoformat(row["ts"]),
                    row["val"]
                ))

            for ag, points in agent_points.items():
                results.append(MetricSeries(
                    name=name,
                    agent=ag,
                    points=points,
                    aggregation=aggregation,
                ))

        return results

    def get_current(self, agent: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Get current values for all metrics."""
        self._flush_buffer()
        
        with self._get_connection() as conn:
            if agent:
                cursor = conn.execute(
                    """SELECT name, agent, value, timestamp, metric_type
                       FROM metrics_current
                       WHERE agent = ?""",
                    (agent,)
                )
            else:
                cursor = conn.execute(
                    """SELECT name, agent, value, timestamp, metric_type
                       FROM metrics_current"""
                )

            result: Dict[str, Dict[str, Any]] = {}
            for row in cursor:
                metric_name = row["name"]
                if metric_name not in result:
                    result[metric_name] = {}
                result[metric_name][row["agent"]] = {
                    "value": row["value"],
                    "timestamp": row["timestamp"],
                    "type": row["metric_type"],
                }

            return result

    def get_agent_metrics(self, agent: str) -> Dict[str, Any]:
        """Get all current metrics for a specific agent."""
        self._flush_buffer()
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                """SELECT name, value, timestamp, metric_type
                   FROM metrics_current
                   WHERE agent = ?""",
                (agent,)
            )

            return {
                row["name"]: {
                    "value": row["value"],
                    "timestamp": row["timestamp"],
                    "type": row["metric_type"],
                }
                for row in cursor
            }

    def _rollup_loop(self) -> None:
        """Background loop for metric rollup."""
        while self._running:
            time.sleep(60)
            
            try:
                self._perform_rollup()
                self._cleanup_old_data()
            except Exception as e:
                logger.error(f"Rollup error: {e}")

    def _perform_rollup(self) -> None:
        """Perform metric rollup from raw to aggregated tables."""
        now = datetime.now()

        with self._get_connection() as conn:
            cutoff_1m = now - timedelta(minutes=1)
            self._rollup_table(conn, "metrics_raw", "metrics_1m", 60, cutoff_1m)

            cutoff_5m = now - timedelta(minutes=5)
            self._rollup_table(conn, "metrics_1m", "metrics_5m", 300, cutoff_5m, is_rollup=True)

            cutoff_1h = now - timedelta(hours=1)
            self._rollup_table(conn, "metrics_5m", "metrics_1h", 3600, cutoff_1h, is_rollup=True)

    def _rollup_table(
        self,
        conn: sqlite3.Connection,
        source_table: str,
        target_table: str,
        bucket_seconds: int,
        cutoff: datetime,
        is_rollup: bool = False,
    ) -> None:
        """Roll up data from source to target table."""
        if is_rollup:
            value_col = "avg_value"
            ts_col = "bucket_start"
        else:
            value_col = "value"
            ts_col = "timestamp"

        bucket_start = cutoff - timedelta(seconds=bucket_seconds)

        conn.execute(f"""
            INSERT OR REPLACE INTO {target_table} 
            (name, agent, avg_value, min_value, max_value, sum_value, count, bucket_start)
            SELECT 
                name,
                agent,
                AVG({value_col}),
                MIN({value_col}),
                MAX({value_col}),
                SUM({value_col}),
                COUNT(*),
                datetime(strftime('%s', {ts_col}) / ? * ?, 'unixepoch') as bucket
            FROM {source_table}
            WHERE {ts_col} < ? AND {ts_col} >= ?
            GROUP BY name, agent, bucket
        """, (bucket_seconds, bucket_seconds, cutoff.isoformat(), bucket_start.isoformat()))

    def _cleanup_old_data(self) -> None:
        """Delete data older than retention period."""
        now = datetime.now()

        with self._get_connection() as conn:
            raw_cutoff = (now - timedelta(hours=1)).isoformat()
            conn.execute("DELETE FROM metrics_raw WHERE timestamp < ?", (raw_cutoff,))

            m1_cutoff = (now - timedelta(days=1)).isoformat()
            conn.execute("DELETE FROM metrics_1m WHERE bucket_start < ?", (m1_cutoff,))

            m5_cutoff = (now - timedelta(days=7)).isoformat()
            conn.execute("DELETE FROM metrics_5m WHERE bucket_start < ?", (m5_cutoff,))

            h1_cutoff = (now - timedelta(days=30)).isoformat()
            conn.execute("DELETE FROM metrics_1h WHERE bucket_start < ?", (h1_cutoff,))

    def get_stats(self) -> Dict[str, Any]:
        """Get collector statistics."""
        with self._get_connection() as conn:
            stats = {}
            
            for table in ["metrics_raw", "metrics_1m", "metrics_5m", "metrics_1h", "metrics_current"]:
                cursor = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                stats[table] = cursor.fetchone()["cnt"]

            cursor = conn.execute("SELECT COUNT(DISTINCT name) as metrics, COUNT(DISTINCT agent) as agents FROM metrics_current")
            row = cursor.fetchone()
            stats["unique_metrics"] = row["metrics"]
            stats["unique_agents"] = row["agents"]

            return {
                "tables": stats,
                "buffer_size": len(self._buffer),
                "running": self._running,
            }


_collector_instance: Optional[MetricsCollector] = None
_collector_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """Get the singleton metrics collector instance."""
    global _collector_instance
    with _collector_lock:
        if _collector_instance is None:
            _collector_instance = MetricsCollector()
        return _collector_instance


def record_metric(
    name: str,
    agent: str,
    value: float,
    metric_type: MetricType = MetricType.GAUGE,
) -> None:
    """Record a metric value."""
    get_metrics_collector().record(name, agent, value, metric_type)


def record_counter(name: str, agent: str, value: float = 1.0) -> None:
    """Record a counter increment."""
    get_metrics_collector().record(name, agent, value, MetricType.COUNTER)


def record_gauge(name: str, agent: str, value: float) -> None:
    """Record a gauge value."""
    get_metrics_collector().record(name, agent, value, MetricType.GAUGE)
