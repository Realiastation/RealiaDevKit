"""Tests pour ws_server.py (ConnectionManager)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from realia_devkit.ws_server import ConnectionManager


class TestWSConnectionManager:
    """5 tests : gestion connexions WebSocket."""

    @pytest.mark.asyncio
    async def test_connect(self):
        """Connexion → channel créé."""
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "task:t1")
        assert "task:t1" in mgr.active_connections
        assert ws in mgr.active_connections["task:t1"]

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Déconnexion → channel nettoyé si vide."""
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "task:t1")
        mgr.disconnect(ws, "task:t1")
        assert "task:t1" not in mgr.active_connections

    @pytest.mark.asyncio
    async def test_broadcast(self):
        """Broadcast → message envoyé à tous les clients."""
        mgr = ConnectionManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect(ws1, "task:t1")
        await mgr.connect(ws2, "task:t1")
        await mgr.broadcast("task:t1", {"event": "test"})
        assert ws1.send_json.called
        assert ws2.send_json.called

    @pytest.mark.asyncio
    async def test_sequence_increment(self):
        """Sequence incrémentée à chaque broadcast."""
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "task:t1")
        await mgr.broadcast("task:t1", {"event": "a"})
        await mgr.broadcast("task:t1", {"event": "b"})
        sent = [call[0][0] for call in ws.send_json.call_args_list]
        assert sent[0]["sequence"] == 1
        assert sent[1]["sequence"] == 2

    @pytest.mark.asyncio
    async def test_channel_isolation(self):
        """Deux channels séparés ne s'affectent pas."""
        mgr = ConnectionManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect(ws1, "task:t1")
        await mgr.connect(ws2, "task:t2")
        await mgr.broadcast("task:t1", {"event": "a"})
        assert ws1.send_json.called
        assert not ws2.send_json.called
