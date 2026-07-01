"""Tests pour ws_broadcaster.py (TaskEventBroadcaster)."""
import pytest
from unittest.mock import patch, AsyncMock
from realia_devkit.ws_broadcaster import TaskEventBroadcaster


class TestWSBroadcaster:
    """5 tests : émission événements WebSocket."""

    @pytest.mark.asyncio
    async def test_emit_started(self):
        """emit_task_started → broadcast appelé."""
        with patch("realia_devkit.ws_broadcaster.manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock()
            await TaskEventBroadcaster.emit_task_started("t1")
            mock_mgr.broadcast.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_emit_progress(self):
        """emit_task_progress → broadcast avec progress_pct calculé."""
        with patch("realia_devkit.ws_broadcaster.manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock()
            await TaskEventBroadcaster.emit_task_progress("t1", 1, 4, "step1")
            args = mock_mgr.broadcast.call_args[0]
            assert args[0] == "task:t1"
            data = args[1]["data"]
            assert data["progress_pct"] == 25.0

    @pytest.mark.asyncio
    async def test_emit_completed(self):
        """emit_task_completed → broadcast avec status=completed."""
        with patch("realia_devkit.ws_broadcaster.manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock()
            await TaskEventBroadcaster.emit_task_completed("t1", {"ok": True}, 1.5)
            data = mock_mgr.broadcast.call_args[0][1]["data"]
            assert data["status"] == "completed"
            assert data["duration_s"] == 1.5

    @pytest.mark.asyncio
    async def test_emit_failed(self):
        """emit_task_failed → broadcast avec error."""
        with patch("realia_devkit.ws_broadcaster.manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock()
            await TaskEventBroadcaster.emit_task_failed("t1", "err", "ValueError", 2)
            data = mock_mgr.broadcast.call_args[0][1]["data"]
            assert data["status"] == "failed"
            assert data["error"] == "err"
            assert data["retry_count"] == 2
