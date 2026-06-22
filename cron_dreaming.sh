#!/bin/bash
# ============================================
# cron_dreaming.sh — Wrapper cron pour le Dream Pipeline
# Exécute dream_pipeline.py et log dans logs/dream_cron.log
# ============================================
set -uo pipefail

BASE_DIR="$(dirname "$(realpath "$0")")"
LOG_DIR="$BASE_DIR/logs"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

mkdir -p "$LOG_DIR"

echo "[$TIMESTAMP] ⏰ Déclenchement du rêve programmé (cron)" >> "$LOG_DIR/dream_cron.log"
cd "$BASE_DIR" || {
    echo "[$TIMESTAMP] ❌ Impossible d'accéder à $BASE_DIR" >> "$LOG_DIR/dream_cron.log"
    exit 1
}

python3 dream_pipeline.py --days 1 >> "$LOG_DIR/dream_cron.log" 2>&1

EXIT_CODE=$?
echo "[$TIMESTAMP] ✅ Rêve terminé (exit code: $EXIT_CODE)" >> "$LOG_DIR/dream_cron.log"
echo "---" >> "$LOG_DIR/dream_cron.log"
exit $EXIT_CODE
