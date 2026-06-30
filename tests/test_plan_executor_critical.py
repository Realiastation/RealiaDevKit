"""Tests des 3 edge cases CRITIQUES du PlanExecutor v1.0.0 (EC-28, EC-03, EC-18)."""
import os, sys
from unittest.mock import MagicMock, patch

# ── Préparation environnement (avant tout import de plan_executor) ──
os.environ.setdefault("UTU_LLM_TYPE", "test")
os.environ.setdefault("UTU_LLM_MODEL", "test")
os.environ.setdefault("UTU_LLM_BASE_URL", "http://localhost:9999")
os.environ.setdefault("UTU_LLM_API_KEY", "test-key")
mock_devkit = MagicMock()
mock_devkit.swapper.swap.return_value = True
sys.modules["devkit_orchestrator"] = mock_devkit  # Force mock meme si reel deja charge

import pytest
from plan_executor import PlanExecutor
from plan_executor_exceptions import (
    PlanExecutionInProgress,
    CircularDependencyError,
    AgentCreationError,
)


class TestCriticalEdgeCases:
    """EC-28, EC-03, EC-18."""

    # ── EC-28 : Exécution concurrente ──
    @pytest.mark.asyncio
    async def test_concurrent_execution_raises_error(self):
        """EC-28: Lock déjà acquis → 2nd appel lève PlanExecutionInProgress."""
        executor = PlanExecutor()
        async with executor._execution_lock:
            with pytest.raises(PlanExecutionInProgress):
                await executor.execute_plan("task test")

    # ── EC-03 : Dépendance circulaire (3 variants) ──
    @pytest.mark.asyncio
    async def test_circular_dependency_simple(self):
        """EC-03: Cycle simple A→B→A détecté."""
        plan = [
            {"step": 1, "action": "chat", "model": "gemma4-12b",
             "instruction": "A", "depends_on": [2]},
            {"step": 2, "action": "chat", "model": "gemma4-12b",
             "instruction": "B", "depends_on": [1]},
        ]
        with pytest.raises(CircularDependencyError):
            PlanExecutor()._detect_circular_dependencies(plan)

    @pytest.mark.asyncio
    async def test_circular_dependency_self(self):
        """EC-03: Auto-dépendance A→A détectée."""
        plan = [
            {"step": 1, "action": "chat", "model": "gemma4-12b",
             "instruction": "A", "depends_on": [1]},
        ]
        with pytest.raises(CircularDependencyError):
            PlanExecutor()._detect_circular_dependencies(plan)

    @pytest.mark.asyncio
    async def test_no_circular_dependency(self):
        """EC-03: Plan sans cycle → pas d'exception."""
        plan = [
            {"step": 1, "action": "chat", "model": "gemma4-12b",
             "instruction": "A"},
            {"step": 2, "action": "chat", "model": "gemma4-12b",
             "instruction": "B", "depends_on": [1]},
        ]
        PlanExecutor()._detect_circular_dependencies(plan)  # Ne doit pas lever

    # ── EC-18 : Échec création agent ──
    @pytest.mark.asyncio
    async def test_agent_creation_fail_raises_error(self):
        """EC-18: SimpleAgent échoue → AgentCreationError (pas de crash)."""
        executor = PlanExecutor()
        step = {
            "step": 1, "action": "chat", "model": "qwen3.6-35b",
            "instruction": "test instruction", "success_criteria": "done",
        }
        with patch("utu.agents.SimpleAgent",
                   side_effect=Exception("VRAM full")):
            with pytest.raises(AgentCreationError) as exc:
                await executor.execute_step(step, {"path": "/tmp/t"})
            assert "VRAM full" in str(exc.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
