"""Broadcaster WebSocket pour PlanExecutor events."""
from realia_devkit.ws_server import manager
from realia_devkit.ws_schemas import (
    WSMessage, TaskStartedEvent, TaskProgressEvent,
    TaskCompletedEvent, TaskFailedEvent,
)
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class TaskEventBroadcaster:
    """Émet événements WebSocket depuis PlanExecutor."""

    @staticmethod
    async def emit_task_started(task_id: str):
        event = TaskStartedEvent(task_id=task_id, status="running",
                                 started_at=datetime.utcnow().isoformat() + "Z")
        msg = WSMessage(channel=f"task:{task_id}", event="task_started",
                        data=event.dict(), timestamp=datetime.utcnow().isoformat() + "Z",
                        sequence=0)
        await manager.broadcast(f"task:{task_id}", msg.dict())
        logger.info(f"Émis task_started: {task_id}")

    @staticmethod
    async def emit_task_progress(task_id: str, step_index: int, step_total: int, step_name: str):
        pct = (step_index / step_total * 100) if step_total > 0 else 0.0
        event = TaskProgressEvent(task_id=task_id, step_index=step_index,
                                  step_total=step_total, step_name=step_name,
                                  progress_pct=pct)
        msg = WSMessage(channel=f"task:{task_id}", event="task_progress",
                        data=event.dict(), timestamp=datetime.utcnow().isoformat() + "Z",
                        sequence=0)
        await manager.broadcast(f"task:{task_id}", msg.dict())
        logger.debug(f"Émis task_progress: {task_id} step {step_index}/{step_total}")

    @staticmethod
    async def emit_task_completed(task_id: str, result: dict, duration_s: float):
        event = TaskCompletedEvent(task_id=task_id, status="completed",
                                   result=result, duration_s=duration_s)
        msg = WSMessage(channel=f"task:{task_id}", event="task_completed",
                        data=event.dict(), timestamp=datetime.utcnow().isoformat() + "Z",
                        sequence=0)
        await manager.broadcast(f"task:{task_id}", msg.dict())
        logger.info(f"Émis task_completed: {task_id}")

    @staticmethod
    async def emit_task_failed(task_id: str, error: str, error_type: str, retry_count: int):
        event = TaskFailedEvent(task_id=task_id, status="failed", error=error,
                                error_type=error_type, retry_count=retry_count,
                                last_attempt_at=datetime.utcnow().isoformat() + "Z")
        msg = WSMessage(channel=f"task:{task_id}", event="task_failed",
                        data=event.dict(), timestamp=datetime.utcnow().isoformat() + "Z",
                        sequence=0)
        await manager.broadcast(f"task:{task_id}", msg.dict())
        logger.error(f"Émis task_failed: {task_id} error={error}")


broadcaster = TaskEventBroadcaster()
