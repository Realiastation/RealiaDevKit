"""Tests des 3 edge cases MOYENS A du PlanExecutor v1.0.0 (EC-19, EC-17, EC-01)."""
import os, sys
from unittest.mock import MagicMock, patch, AsyncMock

os.environ.setdefault("UTU_LLM_TYPE", "test")
os.environ.setdefault("UTU_LLM_MODEL", "test")
os.environ.setdefault("UTU_LLM_BASE_URL", "http://localhost:9999")
os.environ.setdefault("UTU_LLM_API_KEY", "test-key")
mock_devkit = MagicMock()
mock_devkit.swapper.swap.return_value = True
sys.modules["devkit_orchestrator"] = mock_devkit

import pytest, logging
from plan_executor import PlanExecutor
from plan_executor_exceptions import DuplicateStepError


class TestMediumA:
    """EC-19, EC-17, EC-01."""

    # ── EC-19 : Cache fail → dégradation gracieuse ──
    @pytest.mark.asyncio
    async def test_cache_fail_graceful_degradation(self, caplog):
        """EC-19: Cache échoue → warning loggué, pas de crash."""
        caplog.set_level(logging.WARNING)
        executor = PlanExecutor()
        executor.cache = MagicMock()
        executor.cache.restore.side_effect = Exception("Redis down")
        executor.cache.snapshot.side_effect = Exception("Redis down")

        with patch("utu.agents.SimpleAgent") as mock_cls:
            mock_agent = AsyncMock()
            mock_cls.return_value = mock_agent
            mock_agent.__aenter__.return_value = mock_agent
            mock_agent.__aexit__.return_value = None
            mock_agent.run.return_value = MagicMock(
                final_output='[{"step":1,"action":"chat","model":"gemma4-12b","instruction":"test","success_criteria":"ok"}]'
            )
            plan = await executor.generate_plan("test task")
            assert plan is not None
        assert any("Cache" in r.message for r in caplog.records)

    # ── EC-17 : Steps dupliqués → exception ──
    @pytest.mark.asyncio
    async def test_duplicate_steps_raises_error(self):
        """EC-17: Plan avec doublons → DuplicateStepError."""
        plan = [{"step": 1}, {"step": 1}]
        with pytest.raises(DuplicateStepError, match="apparaît plusieurs fois"):
            PlanExecutor()._detect_duplicate_steps(plan)

    @pytest.mark.asyncio
    async def test_no_duplicate_steps(self):
        """EC-17: Plan sans doublons → pas d'exception."""
        plan = [{"step": 1}, {"step": 2}]
        PlanExecutor()._detect_duplicate_steps(plan)

    # ── EC-01 : Plan vide → fallback minimal ──
    @pytest.mark.asyncio
    async def test_empty_plan_fallback(self, caplog):
        """EC-01: Plan vide → fallback 1 étape, pas de crash."""
        caplog.set_level(logging.INFO)
        executor = PlanExecutor()
        with patch.object(executor, "generate_plan", return_value=[]):
            with patch.object(executor, "execute_step", return_value="out"):
                with patch.object(executor, "validate_step",
                                return_value={"status": "pass"}):
                    with patch("utu.agents.SimpleAgent") as mock_cls:
                        mock_agent = AsyncMock()
                        mock_cls.return_value = mock_agent
                        mock_agent.__aenter__.return_value = mock_agent
                        mock_agent.__aexit__.return_value = None

                        result = await executor.execute_plan("test task")
                        assert result is not None
        assert any("Empty plan" in r.message for r in caplog.records)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
