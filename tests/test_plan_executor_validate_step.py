"""Tests pour validate_step() — Couvre les lignes 402-454 (lot 1/4)."""
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


@pytest.fixture
def executor():
    """PlanExecutor avec step_results pre-rempli."""
    e = PlanExecutor()
    e.step_results = {1: {"output": "ok", "file_path": "/tmp/test.py"}}
    return e


class TestValidateStep:
    """4 tests pour validate_step (lignes 402-454)."""

    @pytest.mark.asyncio
    async def test_validate_pass(self, executor, caplog):
        """status=pass → retourne validation + log info."""
        caplog.set_level(logging.INFO)
        step = {"step": 1, "instruction": "test", "success_criteria": "ok"}
        with patch("utu.agents.SimpleAgent") as mock_cls:
            mock_agent = AsyncMock()
            mock_cls.return_value = mock_agent
            mock_agent.__aenter__.return_value = mock_agent
            mock_agent.run.return_value = MagicMock(
                final_output=json.dumps({"status": "pass", "feedback": "OK", "suggested_fix": ""}))
            validation = await executor.validate_step(step, "output")
        assert validation["status"] == "pass"
        assert validation["feedback"] == "OK"
        assert any("SWARM_VALIDATE_PASS" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_validate_fail(self, executor, caplog):
        """status=fail → retourne echec + suggested_fix + log warning."""
        caplog.set_level(logging.WARNING)
        step = {"step": 1, "instruction": "test", "success_criteria": "ok"}
        with patch("utu.agents.SimpleAgent") as mock_cls:
            mock_agent = AsyncMock()
            mock_cls.return_value = mock_agent
            mock_agent.__aenter__.return_value = mock_agent
            mock_agent.run.return_value = MagicMock(
                final_output=json.dumps({"status": "fail", "feedback": "Erreur",
                                        "suggested_fix": "Corrige ligne 5"}))
            validation = await executor.validate_step(step, "output fail")
        assert validation["status"] == "fail"
        assert "Erreur" in validation["feedback"]
        assert "Corrige" in validation["suggested_fix"]
        assert any("SWARM_VALIDATE_FAIL" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_validate_next(self, executor, caplog):
        """status=next → retourne next + log info."""
        caplog.set_level(logging.INFO)
        step = {"step": 1, "instruction": "test", "success_criteria": "ok"}
        with patch("utu.agents.SimpleAgent") as mock_cls:
            mock_agent = AsyncMock()
            mock_cls.return_value = mock_agent
            mock_agent.__aenter__.return_value = mock_agent
            mock_agent.run.return_value = MagicMock(
                final_output=json.dumps({"status": "next", "feedback": "Verifie etape 2"}))
            validation = await executor.validate_step(step, "output")
        assert validation["status"] == "next"
        assert any("SWARM_VALIDATE_NEXT" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_validate_invalid_json(self, executor):
        """JSON invalide → fallback text matching (pass si 'ok' present)."""
        step = {"step": 1, "instruction": "test", "success_criteria": "ok"}
        with patch("utu.agents.SimpleAgent") as mock_cls:
            mock_agent = AsyncMock()
            mock_cls.return_value = mock_agent
            mock_agent.__aenter__.return_value = mock_agent
            mock_agent.run.return_value = MagicMock(final_output="pas du JSON mais ok")
            validation = await executor.validate_step(step, "output")
        assert validation["status"] == "pass"
        assert "feedback" in validation


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
