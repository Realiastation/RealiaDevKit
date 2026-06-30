"""Tests des 3 edge cases MOYENS B du PlanExecutor v1.0.0 (EC-15, EC-24, EC-30)."""
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


class TestMediumB:
    """EC-15, EC-24, EC-30 (dégradations gracieuses)."""

    # ── EC-15 : Modèle inconnu → fallback vers realia_dev ──
    @pytest.mark.asyncio
    async def test_unknown_model_fallback_to_default(self, caplog):
        """EC-15: Modèle inconnu dans config_map → warning + pas de crash."""
        caplog.set_level(logging.WARNING)
        step = {"step": 1, "action": "chat", "model": "unknown_model_xyz",
                "instruction": "test", "success_criteria": "done"}
        with patch("devkit_orchestrator.swapper") as mock_swapper:
            mock_swapper.swap.return_value = True
            with patch("utu.agents.SimpleAgent") as mock_cls:
                mock_agent = AsyncMock()
                mock_cls.return_value = mock_agent
                mock_agent.__aenter__.return_value = mock_agent
                mock_agent.run.return_value = MagicMock(final_output="ok")

                result = await PlanExecutor().execute_step(
                    step, {"path": "/tmp/t"})
                assert result is not None
        assert any("not in config_map" in r.message for r in caplog.records)

    # ── EC-24 : Swap code échoue → fallback vers qwen3.6-35b ──
    @pytest.mark.asyncio
    async def test_code_action_swap_fallback_chain(self, caplog):
        """EC-24: swap qwen3-coder-next fail → fallback qwen3.6-35b."""
        caplog.set_level(logging.WARNING)
        step = {"step": 1, "action": "code", "model": "qwen3-coder-next",
                "instruction": "write code", "success_criteria": "done"}

        def swap_side_effect(model):
            if model == "qwen3-coder-next":
                return False
            if model == "qwen3.6-35b":
                return True
            return False

        with patch("devkit_orchestrator.swapper") as mock_swapper:
            mock_swapper.swap.side_effect = swap_side_effect
            with patch("utu.agents.SimpleAgent") as mock_cls:
                mock_agent = AsyncMock()
                mock_cls.return_value = mock_agent
                mock_agent.__aenter__.return_value = mock_agent
                mock_agent.run.return_value = MagicMock(final_output="out")

                result = await PlanExecutor().execute_step(
                    step, {"path": "/tmp/test.py"})
                assert result is not None
            calls = [c.args[0] for c in mock_swapper.swap.call_args_list]
            assert "qwen3-coder-next" in calls
            assert "qwen3.6-35b" in calls
        assert any("fallback" in r.message.lower() for r in caplog.records)

    # ── EC-30 : Output long → tronqué + marker ──
    @pytest.mark.asyncio
    async def test_long_output_truncated_with_marker(self, caplog):
        """EC-30: Output > 300 chars → troncature + marker + log info."""
        caplog.set_level(logging.INFO)
        executor = PlanExecutor()
        executor.step_results = {
            1: {"output": "A" * 500, "model": "gemma4-12b", "action": "chat",
                "passed": True, "attempts": 1}
        }
        step = {"step": 2, "action": "chat", "model": "gemma4-12b",
                "instruction": "Continuer", "success_criteria": "done"}
        with patch("devkit_orchestrator.swapper") as mock_swapper:
            mock_swapper.swap.return_value = True
            with patch("utu.agents.SimpleAgent") as mock_cls:
                mock_agent = AsyncMock()
                mock_cls.return_value = mock_agent
                mock_agent.__aenter__.return_value = mock_agent
                mock_agent.run.return_value = MagicMock(final_output="out")

                result = await executor.execute_step(step, {"path": "/tmp/t"})
                assert result is not None
        assert any("truncated" in r.message.lower() for r in caplog.records)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
