# RESTART & START GUIDE — DevKit v0.8.0

> Procédure standard pour redémarrer le DevKit Orchestrator et le frontend.
> Le GUI est servi directement par l'orchestrateur sur le port API.

---

## 1. Script Automatique (recommandé)

```bash
./reset_and_start.sh
```

**Ce script :**
1. Tue les processus en cours (`devkit_orchestrator.py`)
2. Purge les `__pycache__` et les logs
3. Lance `devkit_orchestrator.py` (API + GUI sur :8095)
4. Attend que le backend réponde (healthcheck HTTP, timeout 15s)

**Vérification :**
```bash
curl -s http://localhost:8095/health | python3 -m json.tool
```

**GUI :** http://localhost:8095/gui/realia_dev_gui.html

---

## 2. Démarrage Manuel Pas-à-Pas

```bash
# 1. Arrêt complet
pkill -f devkit_orchestrator.py 2>/dev/null
sleep 2

# 2. Nettoyage
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
> devkit.log

# 3. Démarrage orchestrateur (API + GUI)
cd /home/realia/realia-docker/dock-rias-rp
python3 devkit_orchestrator.py &
sleep 3

# 4. Vérification
curl -s http://localhost:8095/health
```

---

## 3. Démarrage du Modèle LLM (llama.cpp)

L'orchestrateur gère automatiquement le swap de modèle sur :9094.
En cas de besoin manuel :

```bash
# Tuer l'ancien processus
pkill -9 llama-server
sleep 2

# Lancer Gemma4 directement
/home/realia/llama.cpp/build/bin/llama-server \
  -m /home/realia/STATION_REALIA/02_MODELS/gguf/google_gemma-4-E4B-it-Q4_K_M.gguf \
  --host 127.0.0.1 --port 9094 -ngl 99 -c 8192 --mmap --flash-attn on &

# Lancer Qwen3-Coder-Next directement
/home/realia/llama.cpp/build/bin/llama-server \
  -m /home/realia/STATION_REALIA/02_MODELS/gguf/Qwen3-Coder-Next-Q4_K_M.gguf \
  --host 127.0.0.1 --port 9094 -ngl 35 -c 8192 --mmap --flash-attn on \
  --cpu-moe --mlock &
```

---

## 4. Vérification des Ports

```bash
lsof -i :8095 -i :9094
```

| Port | Service | Statut attendu |
|------|---------|----------------|
| 8095 | API + GUI (devkit_orchestrator.py) | LISTEN |
| 9094 | llama.cpp (LLM) | LISTEN |

---

## 5. Logs

```bash
tail -f devkit.log                        # Log principal
tail -f /tmp/devkit_startup.log           # Log de démarrage
tail -f /tmp/llama_gemma4-e4b.log         # Modèle Gemma4
tail -f /tmp/llama_qwen3-coder.log        # Modèle Qwen3
```

---

## 6. Résolution de Problèmes

| Problème | Solution |
|----------|----------|
| Port 8095 occupé | `fuser -k 8095/tcp` ou `lsof -i :8095` → `kill -9 <PID>` |
| GUI inaccessible | Vérifier : http://localhost:8095/gui/realia_dev_gui.html |
| llama.cpp ne répond pas | Vérifier `/tmp/llama_*.log` — attendre 60s (modèle 46 Go) |
| Processus zombie | `pkill -9 -f llama-server` puis relancer l'orchestrateur |
| Swarm Monitor vide | L'orchestrateur doit exposer `/models` et `/health` |

---

## 7. Structure des Fichiers Clés

| Fichier | Rôle |
|---------|------|
| `devkit_orchestrator.py` | Backend API + GUI statique (port 8095) |
| `devkit_config.json` | Source de vérité des ports |
| `realia_dev_gui.html` | Frontend complet (PollingUX v2.4 + Swarm Monitor) |
| `reset_and_start.sh` | Script de démarrage |
| `js/swarm-visualizer.js` | Swarm Monitor (placeholder éditeur + mini status) |

---
*Guide v0.8.0 — Mis à jour après stabilisation UI*
