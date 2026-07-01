"""Schemas Pydantic pour WebSocket API Contract v1.0.0"""
from pydantic import BaseModel, Field, validator
from typing import Optional, Literal
from datetime import datetime


class WSMessage(BaseModel):
    """Message WebSocket standard pour tous les channels."""
    channel: str = Field(..., description="Channel: 'monitoring' | 'task:{task_id}' | 'system'")
    event: str = Field(..., description="Type d'événement")
    data: dict = Field(default_factory=dict, description="Payload spécifique")
    timestamp: str = Field(..., description="ISO 8601")
    sequence: int = Field(..., ge=0, description="Numéro de séquence")

    @validator('channel')
    def validate_channel(cls, v):
        valid_prefixes = ['monitoring', 'task:', 'system']
        if not any(v.startswith(p) or v == p for p in valid_prefixes):
            raise ValueError(f"Channel invalide: {v}")
        return v


class TaskStartedEvent(BaseModel):
    """Événement de démarrage de tâche."""
    task_id: str
    status: Literal["running"]
    started_at: str


class TaskProgressEvent(BaseModel):
    """Événement de progression de tâche."""
    task_id: str
    step_index: int
    step_total: int
    step_name: str
    progress_pct: float = Field(ge=0.0, le=100.0)
    eta_seconds: Optional[int] = None


class TaskCompletedEvent(BaseModel):
    """Événement de succès de tâche."""
    task_id: str
    status: Literal["completed"]
    result: dict
    duration_s: float


class TaskFailedEvent(BaseModel):
    """Événement d'échec de tâche."""
    task_id: str
    status: Literal["failed"]
    error: str
    error_type: str
    retry_count: int
    last_attempt_at: str


class WSConfig(BaseModel):
    """Configuration WebSocket (variables d'environnement)."""
    ws_port: int = 8092
    ws_heartbeat_interval_s: int = 30
    ws_max_connections: int = 10
    ws_rate_limit_msg_per_s: int = 100
    ws_reconnect_backoff_base_s: float = 1.0
    ws_reconnect_max_attempts: int = 5
    ws_message_max_size_kb: int = 1024
