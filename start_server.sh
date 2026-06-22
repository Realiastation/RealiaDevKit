#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# start_server.sh — Lancement initial de llama-server (swap séquentiel)
# 
# Ce script démarre UN SEUL processus llama-server sur le port 9094.
# Le swap de modèle est géré par ModelSwapper (dans devkit_orchestrator.py)
# qui fait un kill + restart séquentiel pour libérer la VRAM via CUDA.
#
# Architecture : swap séquentiel validé v0.5-v0.7
#   - Gemma4-E4B  : 4B multimodal, full GPU (ngl=99), ctx=16384
#   - Qwen3-Coder-Next : 80B MoE, CPU (--cpu-moe), 35 layers GPU, ctx=8192
#
# Contrainte VRAM de l'Architecte :
#   UN SEUL modèle chargé à la fois. kill + restart garantit la
#   libération totale VRAM par le driver CUDA.
#
# Usage : ./start_server.sh
#   Arrêt  : pkill -f "llama-server.*port 9094"
#   Swap   : via devkit_orchestrator.py (automatique)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
MODELS_DIR="/etc/realia/models"
SLOT_CACHE_DIR="/var/cache/realia/slots"
LOG_DIR="/var/log/realia"
LLAMA_BIN="llama-server"
HOST="127.0.0.1"
PORT=9094

# Modèle par défaut au démarrage (Qwen3.6-35B = cerveau/routeur)
DEFAULT_MODEL="Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
DEFAULT_MMPROJ=""

# Flags communs (partagés entre tous les modèles)
# Les flags spécifiques (ngl, ctx, cpu-moe, mlock) sont gérés par ModelSwapper
ARGS=(
    "--host" "$HOST"
    "--port" "$PORT"
    "--mmap"                       # Mapping RAM → chargement instantané depuis page cache
    "--cont-batching"              # Traitement batch continu
    "--context-shift"              # Évite les OOM sur sessions longues
    "--slot-save-path" "$SLOT_CACHE_DIR"  # Cache KV persistant via REST API
    "--threads" "8"
)

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   🚀 Realia DevKit — llama-server (swap séquentiel)        ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Architecture : UN SEUL modèle chargé à la fois             ║"
echo "║  Swap : kill + restart → libère 100% VRAM via CUDA         ║"
echo "║  Cache KV : POST /slots/{id}?action=save|restore           ║"
echo "║  Modèles : Q3.6 (35B MoE) / Q3N (80B MoE) / G4E12B (12B) ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Vérifications préalables ────────────────────────────────────────────────
if [ ! -f "$LLAMA_BIN" ]; then
    echo "❌ ERREUR : llama-server introuvable : $LLAMA_BIN"
    exit 1
fi
if [ ! -d "$MODELS_DIR" ]; then
    echo "❌ ERREUR : répertoire modèles introuvable : $MODELS_DIR"
    exit 1
fi
if [ ! -f "$MODELS_DIR/$DEFAULT_MODEL" ]; then
    echo "❌ ERREUR : modèle par défaut introuvable : $MODELS_DIR/$DEFAULT_MODEL"
    exit 1
fi

# ── Vérification que le port est libre ───────────────────────────────────────
if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
    OLD_PID=$(ss -tlnp 2>/dev/null | grep ":$PORT " | grep -oP 'pid=\K[0-9]+' | head -1)
    echo "⚠️  Port $PORT déjà occupé (PID $OLD_PID)."
    echo "   → Utilise 'pkill -f llama-server' ou attends la fin de la session."
    exit 1
fi

# ── Création des répertoires nécessaires ────────────────────────────────────
mkdir -p "$SLOT_CACHE_DIR"
mkdir -p "$LOG_DIR"

# ── Lancement du serveur (Qwen3.6-35B par défaut) ────────────────────────────
echo "🚀 Démarrage de llama-server avec Qwen3.6-35B (cerveau/routeur)..."
echo "   Modèle   : $MODELS_DIR/$DEFAULT_MODEL"
echo "   Slots    : $SLOT_CACHE_DIR"
echo ""

LOGFILE="$LOG_DIR/llama_server.log"
nohup "$LLAMA_BIN" \
    -m "$MODELS_DIR/$DEFAULT_MODEL" \
    -ngl 99 \
    -c 16384 \
    --flash-attn on \
    --cpu-moe \
    --mlock \
    --chat-template chatml \
    "${ARGS[@]}" \
    > "$LOGFILE" 2>&1 &
NEW_PID=$!

echo "   PID      : $NEW_PID"
echo "   Logs     : tail -f $LOGFILE"
echo ""

# ── Attente de disponibilité ────────────────────────────────────────────────
echo -n "   Attente healthcheck "
for i in $(seq 1 30); do
    if curl -sf --max-time 2 "http://$HOST:$PORT/health" >/dev/null 2>&1; then
        echo "✅"
        echo ""
        echo "╔══════════════════════════════════════════════════════════════╗"
        echo "║   ✅ Serveur prêt — $DEFAULT_MODEL chargé           ║"
        echo "║   http://$HOST:$PORT                              ║"
        echo "║   Swap : kill + restart (automatique via API)              ║"
        echo "╚══════════════════════════════════════════════════════════════╝"
        exit 0
    fi
    echo -n "."
    sleep 1
done

echo ""
echo "❌ TIMEOUT : serveur non disponible après 30s"
echo "   Vérifie les logs : tail -f $LOGFILE"
exit 1
