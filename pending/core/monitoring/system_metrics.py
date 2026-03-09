"""
GENESIS System Metrics Agent

Continuously collects system-level metrics and feeds them into
the metrics collector for time-series storage and dashboard display.

Metrics collected:
- CPU: percent, per-core, frequency, load average
- Memory: used, available, percent, swap
- Disk: usage percent, read/write bytes
- Network: bytes sent/received, connections
- Process: GENESIS process memory, CPU, threads, open files

Integrates with:
- MetricsCollector: time-series storage with rollup
- Message bus: broadcasts STATUS_REPORT with system snapshot
- Health monitor: registered as "system_metrics" agent
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.framework.agent_base import AgentBase, AgentConfig, AutonomyLevel
from core.monitoring.metrics import (
    MetricType,
    get_metrics_collector,
)

logger = logging.getLogger(__name__)

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logger.warning("psutil not installed - system metrics collection disabled")


AGENT_NAME = "system_metrics"


@dataclass
class SystemSnapshot:
    """Point-in-time snapshot of system resources."""

    timestamp: datetime
    cpu_percent: float = 0.0
    cpu_per_core: List[float] = field(default_factory=list)
    cpu_freq_mhz: float = 0.0
    cpu_count: int = 0
    load_avg_1m: float = 0.0
    load_avg_5m: float = 0.0
    load_avg_15m: float = 0.0

    mem_total_mb: float = 0.0
    mem_used_mb: float = 0.0
    mem_available_mb: float = 0.0
    mem_percent: float = 0.0
    swap_used_mb: float = 0.0
    swap_percent: float = 0.0

    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    disk_percent: float = 0.0
    disk_read_mb: float = 0.0
    disk_write_mb: float = 0.0

    net_sent_mb: float = 0.0
    net_recv_mb: float = 0.0
    net_connections: int = 0

    proc_pid: int = 0
    proc_memory_mb: float = 0.0
    proc_cpu_percent: float = 0.0
    proc_threads: int = 0
    proc_open_files: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "cpu": {
                "percent": self.cpu_percent,
                "per_core": self.cpu_per_core,
                "freq_mhz": self.cpu_freq_mhz,
                "count": self.cpu_count,
                "load_avg": [self.load_avg_1m, self.load_avg_5m, self.load_avg_15m],
            },
            "memory": {
                "total_mb": self.mem_total_mb,
                "used_mb": self.mem_used_mb,
                "available_mb": self.mem_available_mb,
                "percent": self.mem_percent,
                "swap_used_mb": self.swap_used_mb,
                "swap_percent": self.swap_percent,
            },
            "disk": {
                "used_gb": self.disk_used_gb,
                "total_gb": self.disk_total_gb,
                "percent": self.disk_percent,
                "read_mb": self.disk_read_mb,
                "write_mb": self.disk_write_mb,
            },
            "network": {
                "sent_mb": self.net_sent_mb,
                "recv_mb": self.net_recv_mb,
                "connections": self.net_connections,
            },
            "process": {
                "pid": self.proc_pid,
                "memory_mb": self.proc_memory_mb,
                "cpu_percent": self.proc_cpu_percent,
                "threads": self.proc_threads,
                "open_files": self.proc_open_files,
            },
        }


def _collect_snapshot() -> SystemSnapshot:
    """Collect a point-in-time system snapshot using psutil."""
    if not HAS_PSUTIL:
        return SystemSnapshot(timestamp=datetime.now())

    snap = SystemSnapshot(timestamp=datetime.now())

    # -- CPU --
    snap.cpu_percent = psutil.cpu_percent(interval=0)
    snap.cpu_per_core = psutil.cpu_percent(interval=0, percpu=True)
    snap.cpu_count = psutil.cpu_count() or 0
    freq = psutil.cpu_freq()
    if freq:
        snap.cpu_freq_mhz = freq.current

    load = os.getloadavg()
    snap.load_avg_1m, snap.load_avg_5m, snap.load_avg_15m = load

    # -- Memory --
    mem = psutil.virtual_memory()
    snap.mem_total_mb = round(mem.total / (1024 ** 2), 1)
    snap.mem_used_mb = round(mem.used / (1024 ** 2), 1)
    snap.mem_available_mb = round(mem.available / (1024 ** 2), 1)
    snap.mem_percent = mem.percent

    swap = psutil.swap_memory()
    snap.swap_used_mb = round(swap.used / (1024 ** 2), 1)
    snap.swap_percent = swap.percent

    # -- Disk --
    disk = psutil.disk_usage("/")
    snap.disk_total_gb = round(disk.total / (1024 ** 3), 2)
    snap.disk_used_gb = round(disk.used / (1024 ** 3), 2)
    snap.disk_percent = disk.percent

    try:
        dio = psutil.disk_io_counters()
        if dio:
            snap.disk_read_mb = round(dio.read_bytes / (1024 ** 2), 1)
            snap.disk_write_mb = round(dio.write_bytes / (1024 ** 2), 1)
    except (AttributeError, RuntimeError):
        pass

    # -- Network --
    net = psutil.net_io_counters()
    if net:
        snap.net_sent_mb = round(net.bytes_sent / (1024 ** 2), 1)
        snap.net_recv_mb = round(net.bytes_recv / (1024 ** 2), 1)

    try:
        snap.net_connections = len(psutil.net_connections(kind="inet"))
    except (psutil.AccessDenied, OSError):
        snap.net_connections = 0

    # -- GENESIS process --
    try:
        proc = psutil.Process()
        snap.proc_pid = proc.pid
        snap.proc_memory_mb = round(proc.memory_info().rss / (1024 ** 2), 1)
        snap.proc_cpu_percent = proc.cpu_percent()
        snap.proc_threads = proc.num_threads()
        try:
            snap.proc_open_files = len(proc.open_files())
        except (psutil.AccessDenied, OSError):
            snap.proc_open_files = 0
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return snap


def _record_snapshot(snap: SystemSnapshot) -> None:
    """Push snapshot values into the metrics collector."""
    collector = get_metrics_collector()
    ts = snap.timestamp

    # CPU
    collector.record("sys.cpu.percent", AGENT_NAME, snap.cpu_percent, MetricType.GAUGE, timestamp=ts)
    collector.record("sys.cpu.load_1m", AGENT_NAME, snap.load_avg_1m, MetricType.GAUGE, timestamp=ts)
    collector.record("sys.cpu.load_5m", AGENT_NAME, snap.load_avg_5m, MetricType.GAUGE, timestamp=ts)

    # Memory
    collector.record("sys.mem.percent", AGENT_NAME, snap.mem_percent, MetricType.GAUGE, timestamp=ts)
    collector.record("sys.mem.used_mb", AGENT_NAME, snap.mem_used_mb, MetricType.GAUGE, timestamp=ts)
    collector.record("sys.mem.available_mb", AGENT_NAME, snap.mem_available_mb, MetricType.GAUGE, timestamp=ts)
    collector.record("sys.swap.percent", AGENT_NAME, snap.swap_percent, MetricType.GAUGE, timestamp=ts)

    # Disk
    collector.record("sys.disk.percent", AGENT_NAME, snap.disk_percent, MetricType.GAUGE, timestamp=ts)
    collector.record("sys.disk.read_mb", AGENT_NAME, snap.disk_read_mb, MetricType.COUNTER, timestamp=ts)
    collector.record("sys.disk.write_mb", AGENT_NAME, snap.disk_write_mb, MetricType.COUNTER, timestamp=ts)

    # Network
    collector.record("sys.net.sent_mb", AGENT_NAME, snap.net_sent_mb, MetricType.COUNTER, timestamp=ts)
    collector.record("sys.net.recv_mb", AGENT_NAME, snap.net_recv_mb, MetricType.COUNTER, timestamp=ts)
    collector.record("sys.net.connections", AGENT_NAME, snap.net_connections, MetricType.GAUGE, timestamp=ts)

    # Process
    collector.record("sys.proc.memory_mb", AGENT_NAME, snap.proc_memory_mb, MetricType.GAUGE, timestamp=ts)
    collector.record("sys.proc.cpu_percent", AGENT_NAME, snap.proc_cpu_percent, MetricType.GAUGE, timestamp=ts)
    collector.record("sys.proc.threads", AGENT_NAME, snap.proc_threads, MetricType.GAUGE, timestamp=ts)


class SystemMetricsAgent(AgentBase):
    """
    Agent that continuously collects system metrics.

    Runs on a configurable interval (default 10s), collects CPU/memory/disk/
    network/process metrics, records them in the MetricsCollector for
    time-series storage, and broadcasts a summary on the message bus.
    """

    DEFAULT_INTERVAL = 10.0  # seconds

    def __init__(
        self,
        collection_interval: float = DEFAULT_INTERVAL,
        config: Optional[AgentConfig] = None,
    ):
        if config is None:
            config = AgentConfig(
                agent_name=AGENT_NAME,
                mission="Collect and record system-level resource metrics",
                autonomy_level=AutonomyLevel.FULLY_AUTONOMOUS,
                capabilities={
                    "collect_cpu": True,
                    "collect_memory": True,
                    "collect_disk": True,
                    "collect_network": True,
                    "collect_process": True,
                },
                tools=["psutil"],
                heartbeat_interval=collection_interval,
                error_threshold=10,  # tolerant - metric collection is best-effort
                alert_on_failure=False,
            )
        super().__init__(config)

        self._collection_interval = collection_interval
        self._collector_thread: Optional[threading.Thread] = None
        self._last_snapshot: Optional[SystemSnapshot] = None
        self._collection_count = 0

    # -- AgentBase implementation --

    def execute_task(self, task: Dict[str, Any]) -> Any:
        """Handle on-demand metric requests."""
        task_type = task.get("type", "snapshot")

        if task_type == "snapshot":
            snap = _collect_snapshot()
            _record_snapshot(snap)
            self._last_snapshot = snap
            return snap.to_dict()

        if task_type == "status":
            return {
                "running": self._running,
                "collection_count": self._collection_count,
                "interval": self._collection_interval,
                "last_snapshot": self._last_snapshot.to_dict() if self._last_snapshot else None,
                "psutil_available": HAS_PSUTIL,
            }

        return {"error": f"Unknown task type: {task_type}"}

    def get_health_details(self) -> Dict[str, Any]:
        details = super().get_health_details()
        details.update({
            "collection_count": self._collection_count,
            "interval_seconds": self._collection_interval,
            "psutil_available": HAS_PSUTIL,
            "last_snapshot_time": (
                self._last_snapshot.timestamp.isoformat()
                if self._last_snapshot
                else None
            ),
        })
        return details

    # -- Lifecycle --

    def start(self) -> None:
        super().start()
        self._collector_thread = threading.Thread(
            target=self._collection_loop, daemon=True, name="system-metrics"
        )
        self._collector_thread.start()
        logger.info(
            f"{self.name}: Collecting system metrics every {self._collection_interval}s"
        )

    def stop(self) -> None:
        super().stop()
        if self._collector_thread:
            self._collector_thread.join(timeout=2.0)
        logger.info(f"{self.name}: Stopped after {self._collection_count} collections")

    # -- Collection loop --

    def _collection_loop(self) -> None:
        """Background loop that collects metrics on schedule."""
        while self._running:
            try:
                snap = _collect_snapshot()
                _record_snapshot(snap)
                self._last_snapshot = snap
                self._collection_count += 1
                self._stats["tasks_completed"] += 1

                # Broadcast latest snapshot on message bus
                if self._bus:
                    from core.messaging.message import status_report, HealthStatus

                    msg = status_report(
                        sender=self.name,
                        status=HealthStatus.HEALTHY,
                        details=snap.to_dict(),
                    )
                    self._bus.publish(msg)

            except Exception as e:
                self.handle_error(e, {"phase": "collection"})

            # Sleep in small increments so stop() is responsive
            deadline = time.monotonic() + self._collection_interval
            while self._running and time.monotonic() < deadline:
                time.sleep(0.5)


# -- Singleton --

_instance: Optional[SystemMetricsAgent] = None
_instance_lock = threading.Lock()


def get_system_metrics_agent(
    collection_interval: float = SystemMetricsAgent.DEFAULT_INTERVAL,
) -> SystemMetricsAgent:
    """Get the singleton SystemMetricsAgent."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = SystemMetricsAgent(collection_interval=collection_interval)
        return _instance
