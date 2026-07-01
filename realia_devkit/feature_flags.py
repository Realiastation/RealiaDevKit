"""Feature flags dynamiques pour migration WebSocket."""
from pydantic import BaseModel
import os
import logging

logger = logging.getLogger(__name__)


class FeatureFlags(BaseModel):
    """Feature flags configurables via variables d'environnement."""
    USE_WEBSOCKET: bool = False
    WS_PORT: int = 8092
    WS_MONITORING_PORT: int = 8093
    WS_HEARTBEAT_INTERVAL_S: int = 30
    WS_MAX_CONNECTIONS: int = 10
    WS_RATE_LIMIT_MSG_PER_S: int = 100
    WS_RECONNECT_MAX_ATTEMPTS: int = 5

    @classmethod
    def from_env(cls):
        return cls(
            USE_WEBSOCKET=os.getenv("USE_WEBSOCKET", "false").lower() == "true",
            WS_PORT=int(os.getenv("WS_PORT", "8092")),
            WS_MONITORING_PORT=int(os.getenv("WS_MONITORING_PORT", "8093")),
            WS_HEARTBEAT_INTERVAL_S=int(os.getenv("WS_HEARTBEAT_INTERVAL_S", "30")),
            WS_MAX_CONNECTIONS=int(os.getenv("WS_MAX_CONNECTIONS", "10")),
            WS_RATE_LIMIT_MSG_PER_S=int(os.getenv("WS_RATE_LIMIT_MSG_PER_S", "100")),
            WS_RECONNECT_MAX_ATTEMPTS=int(os.getenv("WS_RECONNECT_MAX_ATTEMPTS", "5")),
        )


flags = FeatureFlags.from_env()


def get_feature_flags() -> dict:
    """Retourne feature flags pour endpoint REST."""
    return flags.dict()
