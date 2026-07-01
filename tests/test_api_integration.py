"""Tests d'intégration API (endpoints existants + WS)."""
import os, sys
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

os.environ.setdefault("USE_WEBSOCKET", "false")

# Mock des dependances externes
sys.modules["skills"] = MagicMock()

# Importer le module réel
import devkit_orchestrator

# Patcher les attributs problématiques
devkit_orchestrator.SwarmRouter = MagicMock()
devkit_orchestrator.UTU_AVAILABLE = False
devkit_orchestrator.TOOL_REGISTRY_AVAILABLE = False
devkit_orchestrator.SWARM_TASKS = {}
devkit_orchestrator.SWARM_QUEUE = type('q', (), {'put': AsyncMock()})()


class TestAPIIntegration:
    """3 tests : backward compat + feature flags."""

    def test_feature_flags_endpoint(self):
        """GET /config/feature-flags retourne dict."""
        client = TestClient(devkit_orchestrator.app)
        resp = client.get("/config/feature-flags")
        assert resp.status_code == 200
        data = resp.json()
        assert "USE_WEBSOCKET" in data
        assert data["USE_WEBSOCKET"] is False

    def test_health_endpoint_exists(self):
        """GET /health fonctionne toujours (backward compat)."""
        client = TestClient(devkit_orchestrator.app)
        resp = client.get("/health")
        assert resp.status_code in (200,)

    def test_swarm_queue_endpoint_exists(self):
        """POST /agent/swarm/queue fonctionne (backward compat)."""
        client = TestClient(devkit_orchestrator.app)
        resp = client.post("/agent/swarm/queue", json={"task": "test"})
        assert resp.status_code in (200, 422)
