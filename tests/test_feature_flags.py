"""Tests pour feature_flags.py."""
import os
from realia_devkit.feature_flags import FeatureFlags, get_feature_flags


class TestFeatureFlags:
    """5 tests : feature flags dynamiques."""

    def test_default_values(self):
        """Valeurs par défaut : USE_WEBSOCKET=False."""
        flags = FeatureFlags()
        assert flags.USE_WEBSOCKET is False
        assert flags.WS_PORT == 8092
        assert flags.WS_HEARTBEAT_INTERVAL_S == 30

    def test_from_env_override(self, monkeypatch):
        """Override USE_WEBSOCKET via env var."""
        monkeypatch.setenv("USE_WEBSOCKET", "true")
        flags = FeatureFlags.from_env()
        assert flags.USE_WEBSOCKET is True

    def test_port_override(self, monkeypatch):
        """Override WS_PORT via env var."""
        monkeypatch.setenv("WS_PORT", "9999")
        flags = FeatureFlags.from_env()
        assert flags.WS_PORT == 9999

    def test_get_feature_flags_returns_dict(self):
        """get_feature_flags retourne un dict."""
        result = get_feature_flags()
        assert isinstance(result, dict)
        assert "USE_WEBSOCKET" in result
        assert "WS_PORT" in result

    def test_all_keys_present(self):
        """Toutes les clés attendues sont présentes."""
        result = get_feature_flags()
        expected = {"USE_WEBSOCKET", "WS_PORT", "WS_MONITORING_PORT",
                    "WS_HEARTBEAT_INTERVAL_S", "WS_MAX_CONNECTIONS",
                    "WS_RATE_LIMIT_MSG_PER_S", "WS_RECONNECT_MAX_ATTEMPTS"}
        assert set(result.keys()) == expected
