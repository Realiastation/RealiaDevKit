#!/usr/bin/env python3
""" Serveur WebSocket pour monitoring en temps réel (logs + VRAM + health).
    Port 8093, endpoint /ws/monitoring.
    Diffusion broadcast à tous les clients connectés.
"""
import asyncio
import json
import time
import logging
import subprocess
from typing import List

try:
    import websockets
except ImportError:
    subprocess.check_call(["pip", "install", "websockets"])
    import websockets

from websockets.server import WebSocketServerProtocol

logging.basicConfig(level=logging.INFO, format="[WS] %(asctime)s %(message)s")
log = logging.getLogger("ws-monitor")

# --- Gestion des connexions ---
connected: List[WebSocketServerProtocol] = []

async def handler(websocket: WebSocketServerProtocol):
    connected.append(websocket)
    log.info(f"Client connecté ({len(connected)} total)")
    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
                if data.get("type") == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected.remove(websocket)
        log.info(f"Client déconnecté ({len(connected)} restants)")

# --- Diffuseurs ---
async def broadcast(msg: dict):
    if not connected:
        return
    payload = json.dumps(msg)
    await asyncio.gather(
        *(ws.send(payload) for ws in connected.copy()),
        return_exceptions=True
    )

async def collect_and_broadcast():
    """Collecte périodiquement les stats et les diffuse."""
    while True:
        try:
            # Health check via l'orchestrateur
            import urllib.request
            try:
                req = urllib.request.Request("http://localhost:8090/health", method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    h = json.loads(resp.read().decode())
            except Exception:
                h = {"status": "error"}

            await broadcast({
                "type": "health",
                "status": "ok" if h.get("status") == "ok" or h.get("current_model") else "error",
                "current_model": h.get("current_model", ""),
                "services": h.get("services", {}),
            })

            # GPU stats
            gpu = h.get("gpu", {})
            vram_total = gpu.get("vram_total_mb", 0)
            vram_used = gpu.get("vram_used_mb", 0)
            if vram_total > 0:
                pct = round(vram_used / vram_total * 100, 1)
                await broadcast({
                    "type": "vram",
                    "used": f"{vram_used/1024:.1f} Go" if vram_used >= 1024 else f"{vram_used:.0f} Mo",
                    "total": f"{vram_total/1024:.1f} Go" if vram_total >= 1024 else f"{vram_total:.0f} Mo",
                    "usedPercent": pct,
                })

        except Exception as e:
            log.warning(f"Erreur collecte: {e}")

        await asyncio.sleep(3)  # toutes les 3s

# --- Logs stream (appelable depuis d'autres processus via pipe) ---
async def log_broadcaster(level: str = "info", message: str = ""):
    """Diffuse un log à tous les clients."""
    await broadcast({
        "type": "log",
        "level": level,
        "message": message,
        "timestamp": time.time(),
    })

# --- Main ---
async def main():
    log.info("Démarrage WS monitor sur ws://0.0.0.0:8093/ws/monitoring")
    async with websockets.serve(handler, "0.0.0.0", 8093):
        await collect_and_broadcast()  # tourne en parallèle

if __name__ == "__main__":
    asyncio.run(main())
