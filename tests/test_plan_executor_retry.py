"""Tests pour boucle retry + next_step (lignes 540-595, lot 2/4)."""
import os, sys, json, pytest, logging
from unittest.mock import MagicMock, patch, AsyncMock

os.environ.setdefault("UTU_LLM_TYPE", "test")
os.environ.setdefault("UTU_LLM_MODEL", "test")
os.environ.setdefault("UTU_LLM_BASE_URL", "http://localhost:9999")
os.environ.setdefault("UTU_LLM_API_KEY", "test-key")
mock_devkit = MagicMock()
mock_devkit.swapper.swap.return_value = True
sys.modules["devkit_orchestrator"] = mock_devkit

from plan_executor import PlanExecutor
from plan_executor_exceptions import PlanExecutorError

# Plan avec action="code" pour ne PAS court-circuiter validate_step
PLAN = [{"step": 1, "model": "gemma4-12b", "action": "code",
         "instruction": "test", "success_criteria": "ok", "depends_on": None}]


class TestRetry:
    """4 tests : retry loop, max_loops, next_step, correction."""

    @pytest.mark.asyncio
    async def test_retry_fail_then_pass(self):
        """execute_step echoue 2x puis reussit → success."""
        e = PlanExecutor()
        with patch.object(e, "generate_plan", return_value=PLAN), \
             patch.object(e, "execute_step", side_effect=[
                 PlanExecutorError("err1"), PlanExecutorError("err2"), "ok"]), \
             patch.object(e, "validate_step", return_value={"status": "pass"}):
            result = await e._execute_plan_impl("test task")
        assert result["success"] is True
        assert result["step_results"]["1"]["attempts"] == 3

    @pytest.mark.asyncio
    async def test_retry_max_loops_reached(self):
        """execute_step echoue toujours → failed_after_retries."""
        e = PlanExecutor()
        with patch.object(e, "generate_plan", return_value=PLAN), \
             patch.object(e, "execute_step", side_effect=PlanExecutorError("fail")):
            result = await e._execute_plan_impl("test task")
        assert result["success"] is False
        assert result["step_results"]["1"]["passed"] is False

    @pytest.mark.asyncio
    async def test_next_step_branch(self):
        """validate_step status=next avec instruction → execute_step supplementaire."""
        e = PlanExecutor()
        exec_calls = []
        async def exec_side(step, ctx=None):
            exec_calls.append(step)
            return "output"
        validate_responses = [
            {"status": "next", "feedback": "...",
             "next_step_instruction": "Fais etape 1.5"},
            {"status": "pass", "feedback": "OK"},
        ]
        with patch.object(e, "generate_plan", return_value=PLAN), \
             patch.object(e, "execute_step", side_effect=exec_side), \
             patch.object(e, "validate_step", side_effect=validate_responses):
            result = await e._execute_plan_impl("test task")
        assert result["success"] is True
        assert len(exec_calls) == 2  # step 1 + step 1.5

    @pytest.mark.asyncio
    async def test_self_correction_with_fix(self):
        """suggested_fix injecte dans l'instruction → retry puis pass."""
        e = PlanExecutor()
        exec_calls = []
        async def exec_side(step, ctx=None):
            exec_calls.append(step.get("instruction", ""))
            return "output"
        validate_responses = [
            {"status": "fail", "feedback": "Erreur",
             "suggested_fix": "Ajouter virgule"},
            {"status": "pass", "feedback": "Corrige"},
        ]
        with patch.object(e, "generate_plan", return_value=PLAN), \
             patch.object(e, "execute_step", side_effect=exec_side), \
             patch.object(e, "validate_step", side_effect=validate_responses):
            result = await e._execute_plan_impl("test task")
        assert result["success"] is True
        assert "Ajouter virgule" in exec_calls[1]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
