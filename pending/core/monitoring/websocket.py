"""
GENESIS WebSocket Real-Time Updates

Provides real-time streaming of monitoring data to dashboards.
"""

from __future__ import annotations
import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class UpdateType(Enum):
    HEALTH = "health"
    METRICS = "metrics"
    ERRORS = "errors"
    ALERTS = "alerts"
    MESSAGES = "messages"
    CIRCUITS = "circuits"
    ALL = "all"


@dataclass
class WebSocketClient:
    websocket: WebSocket
    subscriptions: Set[UpdateType]
    connected_at: datetime
    last_ping: datetime
    client_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "client_id": self.client_id,
            "subscriptions": [s.value for s in self.subscriptions],
            "connected_at": self.connected_at.isoformat(),
            "last_ping": self.last_ping.isoformat(),
        }


class ConnectionManager:
    def __init__(self):
        self._clients: Dict[str, WebSocketClient] = {}
        self._websocket_to_id: Dict[WebSocket, str] = {}
        self._lock = threading.Lock()
        self._client_counter = 0
        self._update_intervals = {
            UpdateType.HEALTH: 5.0,
            UpdateType.METRICS: 10.0,
            UpdateType.ERRORS: 5.0,
            UpdateType.ALERTS: 1.0,
            UpdateType.MESSAGES: 2.0,
            UpdateType.CIRCUITS: 5.0,
        }
        self._running = False

    async def connect(self, websocket: WebSocket, subscriptions: Optional[List[str]] = None) -> str:
        await websocket.accept()
        with self._lock:
            self._client_counter += 1
            client_id = f"client_{self._client_counter}"
            sub_set: Set[UpdateType] = set()
            if subscriptions:
                for s in subscriptions:
                    try:
                        sub_set.add(UpdateType(s))
                    except ValueError:
                        pass
            if not sub_set:
                sub_set = {UpdateType.ALL}
            client = WebSocketClient(
                websocket=websocket,
                subscriptions=sub_set,
                connected_at=datetime.now(),
                last_ping=datetime.now(),
                client_id=client_id,
            )
            self._clients[client_id] = client
            self._websocket_to_id[websocket] = client_id
        logger.info(f"WebSocket client connected: {client_id}")
        await self._send_to_client(client, {
            "type": "connected",
            "client_id": client_id,
            "subscriptions": [s.value for s in sub_set],
            "timestamp": datetime.now().isoformat(),
        })
        return client_id

    def disconnect(self, websocket: WebSocket) -> None:
        with self._lock:
            client_id = self._websocket_to_id.pop(websocket, None)
            if client_id:
                del self._clients[client_id]
                logger.info(f"WebSocket client disconnected: {client_id}")

    async def handle_message(self, websocket: WebSocket, message: str) -> None:
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")
            client_id = self._websocket_to_id.get(websocket)
            if not client_id:
                return
            client = self._clients.get(client_id)
            if not client:
                return
            if msg_type == "ping":
                client.last_ping = datetime.now()
                await self._send_to_client(client, {"type": "pong", "timestamp": datetime.now().isoformat()})
            elif msg_type == "subscribe":
                topics = data.get("topics", [])
                for topic in topics:
                    try:
                        client.subscriptions.add(UpdateType(topic))
                    except ValueError:
                        pass
                await self._send_to_client(client, {
                    "type": "subscribed",
                    "subscriptions": [s.value for s in client.subscriptions],
                })
            elif msg_type == "unsubscribe":
                topics = data.get("topics", [])
                for topic in topics:
                    try:
                        client.subscriptions.discard(UpdateType(topic))
                    except ValueError:
                        pass
                await self._send_to_client(client, {
                    "type": "unsubscribed",
                    "subscriptions": [s.value for s in client.subscriptions],
                })
            elif msg_type == "request":
                update_type = data.get("update_type", "health")
                await self._send_requested_update(client, update_type)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from WebSocket client")
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")

    async def _send_to_client(self, client: WebSocketClient, data: Dict[str, Any]) -> bool:
        try:
            await client.websocket.send_json(data)
            return True
        except Exception as e:
            logger.warning(f"Failed to send to {client.client_id}: {e}")
            return False

    async def _send_requested_update(self, client: WebSocketClient, update_type: str) -> None:
        try:
            ut = UpdateType(update_type)
        except ValueError:
            ut = UpdateType.HEALTH
        data = await self._get_update_data(ut)
        if data:
            await self._send_to_client(client, data)

    async def _get_update_data(self, update_type: UpdateType) -> Optional[Dict[str, Any]]:
        try:
            from .monitor import get_health_monitor
            from .logger import get_error_logger
            from .alerting import get_alert_system
            from core.messaging import get_message_bus
            timestamp = datetime.now().isoformat()
            if update_type == UpdateType.HEALTH:
                monitor = get_health_monitor()
                return {"type": "health", "timestamp": timestamp, "data": monitor.get_all_health()}
            elif update_type == UpdateType.ERRORS:
                error_logger = get_error_logger()
                errors = error_logger.get_recent_errors(limit=10)
                return {"type": "errors", "timestamp": timestamp, "data": {"errors": [e.to_dict() for e in errors], "stats": error_logger.get_error_stats()}}
            elif update_type == UpdateType.ALERTS:
                alerts = get_alert_system()
                return {"type": "alerts", "timestamp": timestamp, "data": {"alerts": alerts.get_recent_alerts(limit=10)}}
            elif update_type == UpdateType.MESSAGES:
                bus = get_message_bus()
                return {"type": "messages", "timestamp": timestamp, "data": {"messages": bus.get_recent_messages(limit=20), "stats": bus.get_stats()}}
            elif update_type == UpdateType.CIRCUITS:
                try:
                    from .circuit_breaker import get_circuit_registry
                    registry = get_circuit_registry()
                    return {"type": "circuits", "timestamp": timestamp, "data": registry.get_all_status()}
                except ImportError:
                    return None
            elif update_type == UpdateType.METRICS:
                try:
                    from .metrics import get_metrics_collector
                    collector = get_metrics_collector()
                    return {"type": "metrics", "timestamp": timestamp, "data": {"current": collector.get_current(), "stats": collector.get_stats()}}
                except ImportError:
                    return None
        except Exception as e:
            logger.error(f"Error getting update data for {update_type}: {e}")
            return None

    async def broadcast(self, update_type: UpdateType, data: Dict[str, Any]) -> int:
        sent_count = 0
        message = {"type": update_type.value, "timestamp": datetime.now().isoformat(), "data": data}
        with self._lock:
            clients = list(self._clients.values())
        disconnected = []
        for client in clients:
            if UpdateType.ALL in client.subscriptions or update_type in client.subscriptions:
                success = await self._send_to_client(client, message)
                if success:
                    sent_count += 1
                else:
                    disconnected.append(client.websocket)
        for ws in disconnected:
            self.disconnect(ws)
        return sent_count

    async def broadcast_health(self, health_data: Dict[str, Any]) -> int:
        return await self.broadcast(UpdateType.HEALTH, health_data)

    async def broadcast_error(self, error_data: Dict[str, Any]) -> int:
        return await self.broadcast(UpdateType.ERRORS, error_data)

    async def broadcast_alert(self, alert_data: Dict[str, Any]) -> int:
        return await self.broadcast(UpdateType.ALERTS, alert_data)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {"connected_clients": len(self._clients), "clients": [c.to_dict() for c in self._clients.values()]}

    def start_background_broadcasts(self) -> None:
        if self._running:
            return
        self._running = True
        asyncio.create_task(self._broadcast_loop())

    async def _broadcast_loop(self) -> None:
        last_broadcast: Dict[UpdateType, float] = {}
        while self._running:
            await asyncio.sleep(1.0)
            now = time.time()
            for update_type, interval in self._update_intervals.items():
                last = last_broadcast.get(update_type, 0)
                if now - last >= interval:
                    data = await self._get_update_data(update_type)
                    if data and self._clients:
                        await self.broadcast(update_type, data.get("data", {}))
                    last_broadcast[update_type] = now

    def stop_background_broadcasts(self) -> None:
        self._running = False


_manager_instance: Optional[ConnectionManager] = None
_manager_lock = threading.Lock()


def get_connection_manager() -> ConnectionManager:
    global _manager_instance
    with _manager_lock:
        if _manager_instance is None:
            _manager_instance = ConnectionManager()
        return _manager_instance


router = APIRouter(prefix="/ws", tags=["websocket"])


@router.websocket("/monitor")
async def websocket_monitor(websocket: WebSocket):
    manager = get_connection_manager()
    client_id = await manager.connect(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            await manager.handle_message(websocket, message)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.get("/stats")
async def get_websocket_stats() -> Dict[str, Any]:
    return get_connection_manager().get_stats()