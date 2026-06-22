#!/usr/bin/env bash
# restart_orchestrator.sh — Redemarrage propre de l'orchestrateur v0.9.2
set -euo pipefail

cd "$(dirname "$0")"
ORCH_LOG="/var/log/realia/orchestrator.log"
ORCH_PID_FILE="/tmp/devkit_orch.pid"

echo "============================================"
echo "  Realia DevKit Orchestrator v0.9.2"
echo "  Redemarrage propre..."
echo "============================================"

# 1) Arret via /shutdown si l'orchestrateur est en ligne
if curl -s --max-time 3 -X POST http://127.0.0.1:8095/shutdown > /dev/null 2>&1; then
    echo "  [1/4] Arret via API /shutdown : OK"
    sleep 3
else
    echo "  [1/4] API /shutdown indisponible, kill direct"
    # Tuer UNIQUEMENT l'orchestrateur, PAS llama-server
    pkill -f "devkit_orchestrator.py" 2>/dev/null || true
    sleep 2
fi

# 2) Liberer UNIQUEMENT le port de l'orchestrateur (8095), PAS celui du LLM (9094)
echo "  [2/4] Liberation du port 8095..."
fuser -k 8095/tcp 2>/dev/null || true
sleep 1

# 3) Demarrer l'orchestrateur
echo "  [3/4] Demarrage de l'orchestrateur..."
python3 devkit_orchestrator.py > "$ORCH_LOG" 2>&1 &
ORCH_PID=$!
echo $ORCH_PID > "$ORCH_PID_FILE"
echo "       PID=$ORCH_PID"

# 4) Attendre la disponibilite
echo "  [4/4] Attente de la disponibilite..."
for i in $(seq 1 30); do
    if curl -s --max-time 2 http://127.0.0.1:8095/health > /dev/null 2>&1; then
        echo "       Pret apres ${i}s"
        curl -s --max-time 2 http://127.0.0.1:8095/health | python3 -c \
            "import sys,json; d=json.load(sys.stdin); print(f'       Version: {d.get(\"version\",\"?\")} | Modeles: {d.get(\"models_count\",\"?\")}')"
        echo ""
        echo "  ✅ Orchestrateur pret sur http://127.0.0.1:8095"
        echo "  Logs: tail -f $ORCH_LOG"
        exit 0
    fi
    sleep 1
done

echo "  ❌ Orchestrateur non disponible apres 30s"
echo "  Logs: tail -50 $ORCH_LOG"
exit 1
