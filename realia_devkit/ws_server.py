"""WebSocket server endpoint pour FastAPI (port 8092)."""
from fastapi import WebSocket, WebSocketDisconnect, APIRouter
from typing import Dict, Set
import asyncio
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """Gère les connexions WebSocket par channel."""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.sequence_counters: Dict[str, int] = {}

    async def connect(self, websocket: WebSocket, channel: str):
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = set()
        self.active_connections[channel].add(websocket)
        self.sequence_counters[channel] = 0
        logger.info(f"WebSocket connecté: channel={channel}")

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self.active_connections:
            self.active_connections[channel].discard(websocket)
            if not self.active_connections[channel]:
                del self.active_connections[channel]
        logger.info(f"WebSocket déconnecté: channel={channel}")

    async def broadcast(self, channel: str, message: dict):
        if channel not in self.active_connections:
            return
        self.sequence_counters[channel] = self.sequence_counters.get(channel, 0) + 1
        message['sequence'] = self.sequence_counters[channel]
        tasks = [self._safe_send(ws, message) for ws in self.active_connections[channel]]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_send(self, websocket: WebSocket, message: dict):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.warning(f"Erreur envoi WebSocket: {e}")


manager = ConnectionManager()


@router.websocket("/ws/task/{task_id}")
async def websocket_task(websocket: WebSocket, task_id: str):
    """Endpoint WebSocket pour suivre progression tâche."""
    channel = f"task:{task_id}"
    await manager.connect(websocket, channel)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel)
