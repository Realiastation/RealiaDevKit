#!/bin/bash
# start.sh — Contrôleur intelligent Station Realia + DevKit
# 🔥 Un seul llama-server sur :9094, swap via orchestrateur
# Usage:
#   ./start.sh              → les deux (Station + DevKit)
#   ./start.sh --station    → seulement Station
#   ./start.sh --devkit     → seulement DevKit
set -uo pipefail

# === Configuration ===
ORCH_PORT=8090
ORCH_SCRIPT="orchestrateur-station.py"
DEVKIT_PORT=8095
DEVKIT_SCRIPT="devkit_orchestrator.py"
WS_PORT=8093
LLAMA_PORT=9094
HTTP_PORT=8092
PID_DIR="/tmp/realia_pids"
BASE="$(dirname "$(realpath "$0")")/.."
LLAMA_BIN="llama-server"

# Modèle par défaut (Gemma4 Vision)
MODEL_PATH="/etc/realia/models/google_gemma-4-E4B-it-Q4_K_M.gguf"
MMPROJ_PATH="/etc/realia/models/mmproj-F16.gguf"

# === Parsing flags ===
MODE="both"
if [ $# -ge 1 ]; then
  case "$1" in
    --station) MODE="station" ;;
    --devkit)  MODE="devkit" ;;
    --both)    MODE="both" ;;
    --help|-h) echo "Usage: $0 [--station|--devkit|--both]"; exit 0 ;;
    *) echo "Option inconnue: $1"; echo "Usage: $0 [--station|--devkit|--both]"; exit 1 ;;
  esac
fi

echo "Mode: $MODE"

wait_for_port() {
    local port=$1 timeout=${2:-30}
    local start=$(date +%s)
    while ! lsof -i":$port" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; do
        if (( $(date +%s) - start > timeout )); then
            echo "Timeout: port $port pas ouvert apres ${timeout}s"
            return 1
        fi
        sleep 1
    done
    echo "Port $port ouvert"
}

cleanup_station() {
    pkill -9 -f "$ORCH_SCRIPT" 2>/dev/null || true
    for port in $ORCH_PORT $WS_PORT $HTTP_PORT; do
        fuser -k "${port}/tcp" 2>/dev/null || true
        lsof -ti":$port" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
    done
}

cleanup_devkit() {
    pkill -9 -f "$DEVKIT_SCRIPT" 2>/dev/null || true
    fuser -k "${DEVKIT_PORT}/tcp" 2>/dev/null || true
    lsof -ti":$DEVKIT_PORT" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
}

start_station() {
    echo ""
    echo "=== Station Realia ==="
    cleanup_station
    sleep 2
    for port in $ORCH_PORT $WS_PORT $HTTP_PORT; do
        if lsof -i":$port" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
            echo "Port $port toujours occupe !"
            lsof -i":$port"
            exit 1
        fi
    done
    echo "Ports Station libres"
    cd "$BASE"
    find "$BASE" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

    # llama.cpp si pas deja actif
    if ! lsof -i":$LLAMA_PORT" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
        echo "Lancement llama.cpp (port $LLAMA_PORT)..."
        if [ ! -f "$MODEL_PATH" ]; then echo "Modele introuvable: $MODEL_PATH"; exit 1; fi
        if [ ! -f "$MMPROJ_PATH" ]; then echo "Projecteur introuvable: $MMPROJ_PATH"; exit 1; fi
        if command -v llama-server &>/dev/null; then RUNNER="llama-server"
        elif [ -f "$LLAMA_BIN" ]; then RUNNER="$LLAMA_BIN"
        else echo "Aucun llama-server trouve"; exit 1; fi
        $RUNNER -m "$MODEL_PATH" --mmproj "$MMPROJ_PATH" --host 0.0.0.0 --port "$LLAMA_PORT" \
            --n-gpu-layers 999 --ctx-size 8192 --cont-batching --verbose > /tmp/llama-server.log 2>&1 &
        echo $! > "$PID_DIR/llama.pid"
        TIMEOUT=60; START_TS=$(date +%s)
        while true; do
            if curl -sf "http://localhost:$LLAMA_PORT/health" > /dev/null 2>&1; then
                echo "llama.cpp actif sur :$LLAMA_PORT"; break; fi
            if [ $(( $(date +%s) - START_TS )) -gt $TIMEOUT ]; then
                echo "Timeout llama.cpp apres ${TIMEOUT}s"; exit 1; fi
            sleep 2
        done
    else
        echo "llama.cpp deja actif sur :$LLAMA_PORT"
    fi

    echo "Serveur HTTP (port $HTTP_PORT)..."
    cd "$BASE/dock-rias-rp"
    if [ -f "devkit_server.py" ]; then python devkit_server.py &
    else python3 -m http.server "$HTTP_PORT" --bind 0.0.0.0 & fi
    echo $! > "$PID_DIR/http.pid"
    wait_for_port $HTTP_PORT 15 || exit 1

    echo "WebSocket (port $WS_PORT)..."
    cd "$BASE/dock-rias-rp"
    if [ -f "devkit_ws_server.py" ]; then python devkit_ws_server.py & fi
    wait_for_port "$WS_PORT" 10 || echo "WebSocket non disponible"

    echo "Orchestrateur Station (port $ORCH_PORT)..."
    cd "$BASE"
    python "$ORCH_SCRIPT" &
    echo $! > "$PID_DIR/orch.pid"
    wait_for_port "$ORCH_PORT" 20 || exit 1
    sleep 2
    echo "Station Realia prete"
}

start_devkit() {
    echo ""
    echo "=== DevKit Orchestrator ==="
    cleanup_devkit
    sleep 2
    if lsof -i":$DEVKIT_PORT" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
        echo "Port $DEVKIT_PORT toujours occupe !"; lsof -i":$DEVKIT_PORT"; exit 1; fi
    echo "Port $DEVKIT_PORT libre"
    cd "$BASE/dock-rias-rp"
    find "$BASE/dock-rias-rp" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    echo "Lancement DevKit (port $DEVKIT_PORT)..."
    python "$DEVKIT_SCRIPT" &
    echo $! > "$PID_DIR/devkit.pid"
    wait_for_port "$DEVKIT_PORT" 20 || exit 1
    echo "DevKit prete sur :$DEVKIT_PORT"
}

# === MAIN ===
mkdir -p "$PID_DIR"

case "$MODE" in
    station) start_station ;;
    devkit)  start_devkit ;;
    both)
        start_station
        echo "--- Lancement DevKit... ---"
        start_devkit
        echo ""
        echo "=== Station + DevKit prets ==="
        echo "   llama.cpp        :9094"
        echo "   UI statique      :8092"
        echo "   WebSocket        :8093"
        echo "   Station          :8090"
        echo "   DevKit           :8095"
        ;;
esac
