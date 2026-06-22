# 🚀 Procédure de Démarrage — DevKit Orchestrator v2.1-contrat

> Document de démarrage à froid pour RealiDev.
> Dernière mise à jour : 2026-06-15

---

## 1. Prérequis

- **Python 3.10+** avec `pydantic`, `fastapi`, `uvicorn`, `httpx`
- **llama.cpp** compilé avec support CUDA et flash-attention
- **Modèles GGUF** dans `~/STATION_REALIA/02_MODELS/gguf/`
- **UTU-Agent** configuré (variables d'env : `UTU_LLM_TYPE`, `UTU_LLM_MODEL`)

---

## 2. Arborescence des fichiers clés

```
dock-rias-rp/
├── devkit_orchestrator.py      # 🧠 Serveur FastAPI (port 8095)
├── contract_manager.py         # 📋 State Machine contrat_travail.json
├── cache_roaming.py            # 🔄 Cache KV roaming
├── plan_executor.py            # 📋 Exécuteur de plans
├── swap_model.sh               # 🔄 Script de swap manuel
├── start_server.sh             # 🚀 Script de démarrage llama-server
├── contrat_travail.json        # 📄 État courant (créé au premier appel)
├── logs/                       # 📝 Logs journaliers (JSONL)
└── docs/
    ├── devkit_architecture.md  # 📖 Documentation complète
    └── STARTUP.md              # 📖 Ce document
```

---

## 3. Démarrage de l'orchestrateur

### 3.1. Démarrer llama-server (modèle par défaut : Q3.6)

```bash
cd ~/realia-docker/dock-rias-rp
./start_server.sh
```

Le script lance `llama-server` sur le port **9094** avec le modèle `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf`.

### 3.2. Démarrer l'orchestrateur

```bash
cd ~/realia-docker/dock-rias-rp
nohup python3 devkit_orchestrator.py > orchestrator.log 2>&1 &
```

L'orchestrateur écoute sur le port **8095**.

---

## 4. Vérifications post-démarrage

### 4.1. Healthcheck du serveur de modèle

```bash
curl -s http://localhost:9094/health
```

**Réponse attendue :** `{"status":"ok",...}` ou `true`

### 4.2. Healthcheck de l'orchestrateur

```bash
curl -s http://localhost:8095/health | python3 -m json.tool
```

**Réponse attendue :** Payload JSON avec `agent.status: "idle"` et `system.metrics.model_actif`

### 4.3. État du contrat de travail

```bash
curl -s http://localhost:8095/contract/status | python3 -m json.tool
```

**Réponse attendue :**
```json
{
    "projet_id": "live",
    "status": "IDLE",
    "workflow": {
        "current_actor": "Q3.6",
        "next_actor_requested": null,
        "reason": "",
        "task_description": "En attente de tâche",
        "consensus_mode": false
    },
    "consensus_requis": ["Q3.6", "Q3N", "G4E12B"],
    "validations_actuelles": {},
    "history": ["Aucun contrat actif. En attente d'une requête."]
}
```

### 4.4. Liste des modèles disponibles

```bash
curl -s http://localhost:8095/models | python3 -m json.tool
```

### 4.5. Test d'inférence simple

```bash
curl -s -X POST http://localhost:8095/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Dis bonjour en français", "model": "qwen3.6"}' | python3 -m json.tool
```

---

## 5. Arrêt propre

```bash
# 1. Tuer l'orchestrateur
pkill -f "devkit_orchestrator.py"

# 2. Tuer llama-server (libère la VRAM)
fuser -k 9094/tcp

# 3. Vérifier la VRAM libérée
nvidia-smi --query-gpu=memory.used --format=csv
```

---

## 6. Logs et debugging

| Fichier | Contenu |
|---|---|
| `orchestrator.log` | Log complet de l'orchestrateur |
| `logs/YYYY-MM-DD.jsonl` | Interactions journalières |
| `contrat_travail.json` | État de la State Machine |
| `/tmp/llama_qwen3.6-35b.log` | Log du serveur llama.cpp |
| `/tmp/llama_qwen3-coder-next.log` | Log du serveur llama.cpp (Q3N) |
| `/tmp/llama_gemma4-12b.log` | Log du serveur llama.cpp (G4E12B) |

---

## 7. Endpoints API

| Méthode | Path | Description |
|---|---|---|
| `GET` | `/health` | Healthcheck orchestrateur |
| `GET` | `/models` | Liste des modèles disponibles |
| `GET` | `/contract/status` | État du contrat de travail |
| `POST` | `/query` | Inférence directe (prompt + model) |
| `POST` | `/agent/swarm/queue` | Ajouter une tâche à la file |
| `GET` | `/swarm/status/{task_id}` | Statut d'une tâche |
| `POST` | `/agent/tool` | Opérations fichier (read/diff/apply) |
| `GET` | `/api/rag/status` | Statut de l'index RAG |
