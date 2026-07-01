"""Tests intégration PlanExecutor → WebSocket Broadcaster."""
import os, sys, json, pytest, logging
from unittest.mock import patch, AsyncMock

os.environ.setdefault("USE_WEBSOCKET", "true")
logging.disable(logging.CRITICAL)

# Mock devkit_orchestrator for import
mock_dk = type("dk", (), {
    "swapper": type("s", (), {"swap": lambda *a, **kw: True})(),
})()
sys.modules["devkit_orchestrator"] = mock_dk

import plan_executor as plan_executor_mod
from plan_executor import PlanExecutor
from plan_executor_exceptions import PlanExecutorError


PLAN = [{"step": 1, "model": "gemma4-12b", "action": "code",
         "instruction": "test", "success_criteria": "ok", "depends_on": None}]


class TestPlanExecutorWS:
    """3 tests : broadcaster appelé pendant execution."""

    @pytest.mark.asyncio
    async def test_progress_emitted_on_loop(self):
        """Boucle retry émet task_progress via broadcaster."""
        plan_executor_mod.flags.USE_WEBSOCKET = True
        e = PlanExecutor()
        with patch("plan_executor.broadcaster") as mock_bc, \
             patch.object(e, "generate_plan", return_value=PLAN), \
             patch.object(e, "execute_step", side_effect=[
                 PlanExecutorError("err"), "ok"]), \
             patch.object(e, "validate_step", return_value={"status": "pass"}):
            mock_bc.emit_task_progress = AsyncMock()
            result = await e._execute_plan_impl("test task", task_id="t1")
            assert result["success"] is True
            mock_bc.emit_task_progress.assert_awaited()

    @pytest.mark.asyncio
    async def test_no_ws_when_disabled(self):
        """USE_WEBSOCKET=false → pas de broadcast."""
        plan_executor_mod.flags.USE_WEBSOCKET = False
        e = PlanExecutor()
        with patch("plan_executor.broadcaster") as mock_bc, \
             patch.object(e, "generate_plan", return_value=PLAN), \
             patch.object(e, "execute_step", return_value="ok"), \
             patch.object(e, "validate_step", return_value={"status": "pass"}):
            mock_bc.emit_task_progress = AsyncMock()
            result = await e._execute_plan_impl("test task", task_id="t1")
            assert result["success"] is True
            mock_bc.emit_task_progress.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_task_id_skips_broadcast(self):
        """Pas de task_id → pas de broadcast."""
        plan_executor_mod.flags.USE_WEBSOCKET = True
        e = PlanExecutor()
        with patch("plan_executor.broadcaster") as mock_bc, \
             patch.object(e, "generate_plan", return_value=PLAN), \
             patch.object(e, "execute_step", side_effect=[
                 PlanExecutorError("err"), "ok"]), \
             patch.object(e, "validate_step", return_value={"status": "pass"}):
            mock_bc.emit_task_progress = AsyncMock()
            result = await e._execute_plan_impl("test task")
            assert result["success"] is True
            mock_bc.emit_task_progress.assert_not_awaited()
