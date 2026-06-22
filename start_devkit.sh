#!/bin/bash
# start_devkit.sh — Lance le DevKit Orchestrator uniquement
# Usage: ./start_devkit.sh
# Dépendances : llama-server doit tourner sur :9094
set -uo pipefail

DEVKIT_PORT=8095
PID_DIR="/tmp/realia_pids"
BASE="$(dirname "$(realpath "$0")")"
LLAMA_PORT=9094

echo "=== DevKit Orchestrator ==="
mkdir -p "$PID_DIR"

# Nettoyage
pkill -9 -f "devkit_orchestrator.py" 2>/dev/null || true
fuser -k "${DEVKIT_PORT}/tcp" 2>/dev/null || true
lsof -ti":$DEVKIT_PORT" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
sleep 2

if lsof -i":$DEVKIT_PORT" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
    echo "ERREUR: Port $DEVKIT_PORT toujours occupe"; lsof -i":$DEVKIT_PORT"; exit 1; fi
echo "Port $DEVKIT_PORT libre"

# Verifier llama-server
if ! lsof -i":$LLAMA_PORT" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
    echo "ATTENTION: Aucun llama-server sur :$LLAMA_PORT"
    echo "Lance d'abord swap_model.sh ou start_station.sh"
fi

cd "$BASE"
find "$BASE" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# DevKit
echo "Lancement DevKit :$DEVKIT_PORT..."
python devkit_orchestrator.py &
echo $! > "$PID_DIR/devkit.pid"
sleep 5

echo ""
echo "=== DevKit prete ==="
echo "   DevKit            :$DEVKIT_PORT"
echo "   Docs              :http://localhost:$DEVKIT_PORT/docs"
