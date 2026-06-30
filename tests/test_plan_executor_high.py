"""Tests des 4 edge cases HAUTES du PlanExecutor v1.0.0 (EC-02, EC-04, EC-07, EC-13)."""
import os, sys, asyncio
from unittest.mock import MagicMock, patch

# ── Préparation environnement (avant tout import de plan_executor) ──
os.environ.setdefault("UTU_LLM_TYPE", "test")
os.environ.setdefault("UTU_LLM_MODEL", "test")
os.environ.setdefault("UTU_LLM_BASE_URL", "http://localhost:9999")
os.environ.setdefault("UTU_LLM_API_KEY", "test-key")
mock_devkit = MagicMock()
mock_devkit.swapper.swap.return_value = True
sys.modules["devkit_orchestrator"] = mock_devkit  # Force mock

import pytest
from plan_executor import PlanExecutor
from plan_executor_exceptions import (
    InvalidStepError, ModelSwapError, LLMTimeoutError,
)


class TestHighEdgeCases:
    """EC-02, EC-04, EC-07, EC-13."""

    # ── EC-02 : Instruction manquante ──
    @pytest.mark.asyncio
    async def test_missing_instruction_raises_error(self):
        """EC-02: step sans instruction → InvalidStepError."""
        step = {"step": 1, "action": "chat", "model": "gemma4-12b"}
        with pytest.raises(InvalidStepError, match="Instruction manquante"):
            await PlanExecutor().execute_step(step)

    @pytest.mark.asyncio
    async def test_empty_instruction_raises_error(self):
        """EC-02: instruction vide → InvalidStepError."""
        step = {"step": 1, "action": "chat", "model": "gemma4-12b",
                "instruction": ""}
        with pytest.raises(InvalidStepError, match="Instruction manquante"):
            await PlanExecutor().execute_step(step)

    # ── EC-13 : Code sans file_path ──
    @pytest.mark.asyncio
    async def test_code_action_without_file_path_raises_error(self):
        """EC-13: action=code sans file_path → InvalidStepError."""
        step = {"step": 1, "action": "code", "model": "qwen3-coder-next",
                "instruction": "Écrire une fonction"}
        with pytest.raises(InvalidStepError, match="file_path manquant"):
            await PlanExecutor().execute_step(step)

    # ── EC-04 : Swap échoue ──
    @pytest.mark.asyncio
    async def test_swap_fail_raises_model_swap_error(self):
        """EC-04: swapper.swap() False → ModelSwapError."""
        step = {"step": 1, "action": "chat", "model": "gemma4-12b",
                "instruction": "test", "success_criteria": "done"}
        with patch("devkit_orchestrator.swapper") as mock_swapper:
            mock_swapper.swap.return_value = False
            with pytest.raises(ModelSwapError, match="Impossible de charger"):
                await PlanExecutor().execute_step(step, {"path": "/tmp/t"})

    # ── EC-07 : Timeout LLM ──
    @pytest.mark.asyncio
    async def test_llm_timeout_raises_error(self):
        """EC-07: LLM > 60s → LLMTimeoutError (mock instantané)."""
        step = {"step": 1, "action": "chat", "model": "gemma4-12b",
                "instruction": "test", "success_criteria": "done"}
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            with patch("utu.agents.SimpleAgent") as mock_agent_cls:
                mock_agent_cls.return_value.__aenter__.return_value = None
                with pytest.raises(LLMTimeoutError, match="Timeout après 60s"):
                    await PlanExecutor().execute_step(step, {"path": "/tmp/t"})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
