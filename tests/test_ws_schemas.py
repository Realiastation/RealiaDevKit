"""Tests pour ws_schemas.py (API Contract v1.0.0)."""
import pytest
from pydantic import ValidationError
from realia_devkit.ws_schemas import (
    WSMessage, TaskStartedEvent, TaskProgressEvent,
    TaskCompletedEvent, TaskFailedEvent, WSConfig,
)
from datetime import datetime


class TestWSSchemas:
    """5 tests : validation des schemas WebSocket."""

    def test_valid_task_progress(self):
        """Schema task_progress valide."""
        e = TaskProgressEvent(task_id="t1", step_index=1, step_total=5,
                              step_name="plan", progress_pct=20.0)
        assert e.step_index == 1
        assert e.progress_pct == 20.0

    def test_invalid_progress_pct(self):
        """progress_pct hors limites → ValidationError."""
        with pytest.raises(ValidationError):
            TaskProgressEvent(task_id="t1", step_index=1, step_total=5,
                              step_name="plan", progress_pct=150.0)

    def test_valid_ws_message(self):
        """WSMessage valide avec channel task:."""
        msg = WSMessage(channel="task:t1", event="task_started",
                        data={}, timestamp="2026-07-01T12:00:00Z", sequence=0)
        assert msg.channel == "task:t1"
        assert msg.sequence == 0

    def test_invalid_channel(self):
        """Channel inconnu → ValidationError."""
        with pytest.raises(ValidationError):
            WSMessage(channel="unknown", event="x", data={},
                      timestamp="2026-07-01T12:00:00Z", sequence=0)

    def test_ws_config_defaults(self):
        """WSConfig valeurs par défaut."""
        c = WSConfig()
        assert c.ws_port == 8092
        assert c.ws_heartbeat_interval_s == 30
        assert c.ws_message_max_size_kb == 1024
