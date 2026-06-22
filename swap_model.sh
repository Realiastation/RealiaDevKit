#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# swap_model.sh v2.2 — Optimisé pour Llama.cpp (Gemma4 & Qwen3-Coder-Next 80B MoE)
# 
# Usage : ./swap_model.sh <model_name>
#   model_name : "gemma4-e4b" | "qwen3-coder-next"
#
# Architecture :
#   Gemma4-E4B  : 4B, full GPU (ngl=999), multimodal (mmproj), haute créativité
#   Qwen3-Coder-Next : 80B MoE, CPU为主 (RAM), experts actifs sur GPU (ngl=35)
#
# Swap = kill → restart avec le nouveau GGUF → layers GPU reload
# Temps de swap : ~1-3 secondes (mmap depuis 128GB RAM, pas de relecture disque)
#
# Changements v2.2 :
#   - n_gpu_layers=35 pour Q3N 80B (sweet spot 16GB VRAM)
#   - flash-attn pour LES DEUX modèles (pas seulement Q3N)
#   --ctx-size 16384 pour Gemma4
#   --context-shift pour éviter OOM sur sessions longues
#   --threads 8 pour Q3N (optimisé CPU MoE)
#   --batch-size 512 explicite
#   Détection VRAM comme filet de sécurité
# ──────────────────────────────────────────────────────────────────────────────
set -e

MODELS_DIR="/etc/realia/models"
HOST="127.0.0.1"
PORT=9094
LLAMA_BIN="llama-server"
LOG_DIR="/var/log/realia"

# ── Mapping modèle → GGUF ────────────────────────────────────────────────────
declare -A MODEL_MAP
MODEL_MAP["qwen3.6-35b"]="Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
MODEL_MAP["qwen3-coder-next"]="Qwen3-Coder-Next-Q4_K_M.gguf"
MODEL_MAP["gemma4-12b"]="gemma-4-12b-it-Q4_K_M.gguf"

declare -A MMPROJ_MAP
MMPROJ_MAP["gemma4-12b"]="mmproj-gemma4-12b-F16.gguf"

# ── Arguments ─────────────────────────────────────────────────────────────────
MODEL_NAME="${1,,}"  # lowercase
MODEL_FILE="${MODEL_MAP[$MODEL_NAME]}"

if [ -z "$MODEL_FILE" ]; then
    echo "SWAP_ERROR | modèle inconnu: '$1'"
    echo "Modèles disponibles: ${!MODEL_MAP[*]}"
    exit 1
fi

MODEL_PATH="$MODELS_DIR/$MODEL_FILE"
if [ ! -f "$MODEL_PATH" ]; then
    echo "SWAP_ERROR | fichier introuvable: $MODEL_PATH"
    exit 1
fi

# ── 1. Détection VRAM (Filet de sécurité) ────────────────────────────────────
VRAM_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,nounits,noheader 2>/dev/null | head -1 || echo "0")
echo "SWAP_VRAM | ${VRAM_FREE}MB libre"

# ── 2. Configuration dynamique par modèle ────────────────────────────────────
CTX_SIZE=8192
GPU_LAYERS=999
THREADS=16
ARGS=()

case "$MODEL_NAME" in
    "qwen3.6-35b")
        echo "SWAP_CFG | Qwen3.6 35B A3B (MoE, Cerveau/Router)"
        CTX_SIZE=16384
        GPU_LAYERS=99
        THREADS=8
        ARGS+=(
            "--cpu-moe"
            "--mlock"
            "--flash-attn" "on"
        )
        ;;
    "gemma4-12b")
        echo "SWAP_CFG | Gemma4 12B (Multimodal, Expert UI/Analyse)"
        CTX_SIZE=16384
        GPU_LAYERS=999
        THREADS=8
        ARGS+=(
            "--mmproj" "$MODELS_DIR/mmproj-gemma4-12b-F16.gguf"
            "--mlock"
            "--flash-attn" "on"
        )
        ;;
    "qwen3-coder-next")
        echo "SWAP_CFG | Qwen3-Coder-Next (80B MoE, RAM为主, Experts sur GPU)"
        CTX_SIZE=8192
        GPU_LAYERS=35        # Sweet spot 16GB VRAM — experts actifs GPU, reste CPU
        THREADS=8            # Optimisé calcul CPU des couches non déportées
        ARGS+=(
            "--cpu-moe"       # Gestion MoE optimisée CPU
            "--mlock"         # OBLIGATOIRE : verrouille 80B en RAM, évite swap OS
            "--flash-attn" "on" # Optimise cache KV des experts en VRAM
        )
        # Filet de sécurité VRAM : si <12GB libre, on reduit les layers GPU
        if [ "$VRAM_FREE" -gt 0 ] && [ "$VRAM_FREE" -lt 12000 ]; then
            echo "SWAP_VRAM_WARN | VRAM faible (${VRAM_FREE}MB) — réduction ngl à 28"
            GPU_LAYERS=28
        fi
        ;;
    *)
        echo "SWAP_CFG | Modèle inconnu, paramètres par défaut"
        ;;
esac

# ── 3. Flags communs d'optimisation ──────────────────────────────────────────
ARGS+=(
    "--host" "$HOST"
    "--port" "$PORT"
    "--ctx-size" "$CTX_SIZE"
    "--n-gpu-layers" "$GPU_LAYERS"
    "--threads" "$THREADS"
    "--batch-size" "512"
    "--mmap"
    "--cont-batching"
    "--context-shift"
)

echo "SWAP_START | model=$MODEL_NAME | gguf=$MODEL_FILE | ctx=$CTX_SIZE | ngl=$GPU_LAYERS | threads=$THREADS"

# ── 4. Arrêt de l'ancien serveur ─────────────────────────────────────────────
LLAMA_PID=$(pgrep -f "llama-server.*port $PORT" 2>/dev/null || true)
if [ -n "$LLAMA_PID" ]; then
    echo "SWAP_KILL | pid=$LLAMA_PID"
    kill "$LLAMA_PID" 2>/dev/null || true
    for i in $(seq 1 10); do
        if ! ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
            break
        fi
        sleep 0.5
    done
    sleep 0.5
fi

# ── 5. Lancement du nouveau serveur ──────────────────────────────────────────
mkdir -p "$LOG_DIR"
echo "SWAP_LAUNCH | ${LLAMA_BIN} --model ${MODEL_PATH} ${ARGS[*]}"
nohup "$LLAMA_BIN" \
    --model "$MODEL_PATH" \
    "${ARGS[@]}" \
    > "$LOG_DIR/llama_${MODEL_NAME}.log" 2>&1 &
NEW_PID=$!
echo "SWAP_STARTED | pid=$NEW_PID | model=$MODEL_NAME"

# ── 6. Attente de disponibilité ──────────────────────────────────────────────
echo -n "SWAP_WAIT "
for i in $(seq 1 30); do
    if curl -sf --max-time 1 "http://$HOST:$PORT/v1/models" >/dev/null 2>&1; then
        echo ""
        echo "SWAP_READY | model=$MODEL_NAME | pid=$NEW_PID | time=${i}s"
        exit 0
    fi
    echo -n "."
    sleep 1
done

echo ""
echo "SWAP_TIMEOUT | model=$MODEL_NAME | pid=$NEW_PID | après 30s"
exit 1
