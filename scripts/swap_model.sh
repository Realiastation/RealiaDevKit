#!/usr/bin/env bash
# Swap GGUF Model on llama.cpp server (port unique 9094)
# Usage: ./swap_model.sh <model_alias> [port]
set -euo pipefail

MODEL_ALIAS="${1:-gemma4-e4b}"
PORT="${2:-9094}"
LOG_DIR="/home/realia/realia-docker/dock-rias-rp/logs"
LLAMA_BIN="/home/realia/llama.cpp/build/bin/llama-server"
GGUF_DIR="/home/realia/STATION_REALIA/02_MODELS/gguf"

mkdir -p "$LOG_DIR"

declare -A MODEL_PATHS=(
  ["gemma4-e4b"]="$GGUF_DIR/google_gemma-4-E4B-it-Q4_K_M.gguf"
  ["qwen3-coder-next"]="$GGUF_DIR/Qwen3-Coder-Next-Q4_K_M.gguf"
)

declare -A MODEL_MMPROJ=(
  ["gemma4-e4b"]="$GGUF_DIR/mmproj-F16.gguf"
  ["qwen3-coder-next"]=""
)

MODEL_FILE="${MODEL_PATHS[$MODEL_ALIAS]:-}"
if [[ -z "$MODEL_FILE" ]]; then
  echo "[SWAP_ERR] Unknown model alias: $MODEL_ALIAS"
  exit 1
fi
if [[ ! -f "$MODEL_FILE" ]]; then
  echo "[SWAP_ERR] File not found: $MODEL_FILE"
  exit 1
fi

# Port check — set +e pour éviter que grep exit 1 ne tue le script
set +e
ss_check=$(ss -tlnp 2>/dev/null)
set -e
if echo "$ss_check" | grep -q ":$PORT "; then
  echo "[SWAP] Port $PORT occupé, arrêt du serveur..."
  set +e
  pkill -f "llama-server.*--port $PORT" 2>/dev/null || true
  set -e
  sleep 2
  set +e
  ss_check2=$(ss -tlnp 2>/dev/null)
  set -e
  if echo "$ss_check2" | grep -q ":$PORT "; then
    set +e
    pkill -9 -f "llama-server.*--port $PORT" 2>/dev/null || true
    set -e
    sleep 1
  fi
else
  echo "[SWAP] Port $PORT est libre"
fi

echo "[SWAP] Starting $MODEL_ALIAS on :$PORT..."
CMD=("$LLAMA_BIN" -m "$MODEL_FILE" --host 127.0.0.1 --port "$PORT" --n-gpu-layers 999 --ctx-size 8192 --cont-batching)

# DevSenior: flags MoE pour Qwen3-Coder-Next
if [[ "$MODEL_ALIAS" == "qwen3-coder-next" ]]; then
  CMD+=(--cpu-moe --mlock --flash-attn on)
fi

MMPROJ="${MODEL_MMPROJ[$MODEL_ALIAS]:-}"
if [[ -n "$MMPROJ" && -f "$MMPROJ" ]]; then
  CMD+=(--mmproj "$MMPROJ")
fi

nohup "${CMD[@]}" > "$LOG_DIR/llama_${MODEL_ALIAS}.log" 2>&1 &
PID=$!
echo "[SWAP] PID=$PID"

# HEALTH CHECK with retry
MAX_WAIT=40
INTERVAL=1
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
  if curl -s -f -m 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "[SWAP_OK] $MODEL_ALIAS ready on :$PORT (${ELAPSED}s)"
    exit 0
  fi
  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))
done

echo "[SWAP_ERR] Health check timeout after ${MAX_WAIT}s for $MODEL_ALIAS"
exit 1
