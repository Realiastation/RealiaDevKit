# 🚀 RUNBOOK — Realia DevKit v0.9.3

> Architecture Swap Séquentiel : un seul modèle à la fois en VRAM, kill + restart.
> Tools & Skills Layer : Gemma4 (routeur) + Qwen3 (exécuteur) avec Tool Loop JSON-Flash.
> Archive Skill : `archive_skill.py` condense les logs JSONL pour le rêveur nocturne.
> Dream Pipeline : `dream_pipeline.py` consolide la mémoire dans `state_memoire.json` (t=0.1).
> Swarm Monitor intégré dans le placeholder de l'éditeur.

---

## 1. Architecture

```
+-- DevKit Orchestrator (:8095) -------------------------------+
| POST /v1/chat/completions -> Tool Loop -> tools_registry      |
| Swap séquentiel -> llama-server (:9094)                     |
| GUI statique : /gui/realia_dev_gui.html                      |
+-- tools_registry.py (6 outils sandbox) ----------------------+
| read_file (path|filepath), write_file (+backup .bak.realia)   |
| list_files (path), execute_shell (cmd|command, whitelistée)   |
| fetch_url (url, timeout 15s), query_rag (query, top_k)       |
+-- Tool Loop (process_with_tools) ----------------------------+
| Iter 1: LLM -> tool_call -> Python execute                    |
| Résultat injecté dans messages (role: tool)                   |
| Iter 2: LLM -> réponse finale sans tool_call                  |
| MAX_TOOL_ITERATIONS = 5, 3 retries max par étape              |
+---------------------------------------------------------------+
+-- Swarm Monitor (frontend) ----------------------------------+
| #swarm-visualizer dans l'éditeur (placeholder)               |
| #swarm-mini dans la barre model-status (compact)             |
| Polling /models + /health toutes les 2s                      |
| Swap détecté et affiché en direct                            |
+---------------------------------------------------------------+
```

## 2. Démarrage

```bash
# Automatique (recommandé)
cd /home/realia/realia-docker/dock-rias-rp
./reset_and_start.sh

# Manuel
python3 devkit_orchestrator.py &

# Vérification
curl -s http://localhost:8095/health | python3 -m json.tool

# GUI
http://localhost:8095/gui/realia_dev_gui.html
```

## 3. Tool Loop (JSON-Flash)

**Gemma4 (Médiateur externe)** : explore, RAG, rapports
**Qwen3 (Expert Code interne)** : lit, corrige, teste

```bash
# Qwen3 lit un fichier
curl -X POST http://localhost:8095/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen3-coder", "messages": [{"role": "user", "content": "Lis tools_registry.py, combien d'outils ?"}], "max_tokens": 2048}'

# Gemma4 explore
curl -X POST http://localhost:8095/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gemma4", "messages": [{"role": "system", "content": "Tu peux utiliser fetch_url."}, {"role": "user", "content": "Va voir la doc sur :8095/docs."}], "max_tokens": 4096}'
```

## 4. Hot-Swap (API HTTP)

```bash
# Charger Gemma4 (défaut)
curl -X POST http://localhost:8095/models/load -H "Content-Type: application/json" -d '{"model": "gemma4"}'

# Charger Qwen3 (~8s)
curl -X POST http://localhost:8095/models/load -H "Content-Type: application/json" -d '{"model": "qwen3-coder"}'

# Lister les modèles
curl -s http://localhost:8095/models | python3 -m json.tool
```

## 5. Presets par Modèle

Fichier : `start_server.sh` (flags Gemma4 par défaut)
Fichier : `archive_skill.py` (condensation logs JSONL)

| Modèle | Flags | Rôle |
|--------|-------|------|
| Gemma4 | -ngl 99 --flash-attn --reasoning auto | Médiateur (externe) |
| Qwen3-Coder | -ngl 35 --cpu-moe --mlock | Expert Code (interne) |

## 6. Outils Disponibles

| Outil | Arguments | Sécurité |
|-------|-----------|----------|
| read_file | path ou filepath, max | Sandbox /dock-rias-rp |
| write_file | path, content | Backup .bak.realia |
| list_files | path | Sandbox |
| execute_shell | cmd ou command | Whitelist caractères dangereux |
| fetch_url | url, max | HTTP/HTTPS only, timeout 15s |
| query_rag | query, top_k | Index /rag/index.jsonl |

## 7. Endpoints API

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| /health | GET | Statut du serveur, modèles chargés |
| /status | GET | Statistiques (tâches, modèles, cache) |
| /models | GET | Liste des modèles avec statut |
| /slots | GET | Monitoring des slots d'inférence |
| /models/load | POST | Charger un modèle à chaud |
| /v1/chat/completions | POST | Chat avec Tool Loop |
| /agent/swarm/queue | POST | Ajouter une tâche swarm |
| /agent/swarm/queue | GET | Dernière tâche terminée (polling) |
| /agent/swarm/plan | POST | PlanExecutor |
| /api/task/{id}/status | GET | Statut détaillé d'une tâche |
| /api/files | GET | Liste des fichiers du projet |
| /api/file | GET | Contenu d'un fichier |
| /api/save-file | POST | Sauvegarder un fichier |
| /api/delete-file | POST | Supprimer un fichier |
| /api/logs | GET | Logs du backend |
| /gui/... | GET | Frontend statique (HTML, JS, CSS) |

## 8. Swarm Monitor (Frontend)

Le **Swarm Monitor** s'affiche dans le placeholder de l'éditeur
(rectangle central, "Sélectionnez un fichier ou basculez en mode Logs").

**Fonctionnement :**
- Polling `/models` + `/health` toutes les 2 secondes
- Affiche le modèle actif (🧠 nom_du_modèle)
- Affiche les outils disponibles (🔧 rag · vision · terminal)
- Détecte les swaps de modèle et les affiche en temps réel
- Mini indicateur compact dans la barre `#model-status` (en bas du chat)

**Fichier :** `js/swarm-visualizer.js` (v3.0)

## 9. Communication GUI ↔ Backend

Le frontend utilise **Polling UX v2.4** :

1. Envoie un message → `POST /agent/swarm/queue`
2. **Polling** toutes les 1.5s sur `GET /api/task/{id}/status`
3. Chaque requête de polling a un `AbortSignal.timeout(10000)` pour éviter les fetch pendus
4. Extrait `step_results.text` par ordre de priorité
5. Arrêt du polling après **120s** (timeout général)
6. Fallback conversationnel

**Backend :** `_call_utu()` enveloppé dans `asyncio.wait_for(timeout=300.0)` pour éviter les générations LLM qui pendent.

**Propreté :** dédoublonnage par `lastSeenText`, nettoyage auto des JSON bruts toutes les 2s.

**⚠️ Attention :** `pollStatus()` (diagnostic interne) n'affiche plus d'erreurs dans le chat pour ne pas polluer la conversation. Le vrai timeout est géré par `sendMessage()`.

## 10. Fichiers Clés

| Fichier | Rôle |
|---------|------|
| `devkit_orchestrator.py` | Backend API FastAPI (port 8095) |
| `devkit_config.json` | Source de vérité des ports |
| `realia_dev_gui.html` | Frontend complet (PollingUX v2.4 + Swarm Monitor) |
| `reset_and_start.sh` | Script de démarrage |
| `start.sh` | Contrôleur intelligent (Station + DevKit) |
| `js/swarm-visualizer.js` | Swarm Monitor v3.0 |
| `tools_registry.py` | Registre des 6 outils sandbox |

## 11. Logs

```bash
tail -f devkit.log                         # Log principal
tail -f /tmp/devkit_startup.log            # Log de démarrage
tail -f /tmp/llama_*.log                   # Logs llama.cpp
grep "TOOL_" devkit.log                    # Logs Tool Loop
grep "SWAP_" devkit.log                    # Logs Swap
```

---

## 🛡️ Dépannage Rapide

| Problème | Solution |
|----------|----------|
| Backend down | `./reset_and_start.sh` |
| GUI :8095 inaccessible | Vérifier que l'orchestrateur tourne (`curl :8095/health`) |
| Message JSON au lieu de texte | Le PollingUX v2.4 nettoie automatiquement |
| Swarm Monitor vide | Vérifier `/models` et `/health` exposés |
| Vision inactive | Vérifier que le backend expose `vision` dans `tools` |
| Modèle non chargé | `curl -X POST :8095/models/load -d '{"model":"gemma4"}'` |

---
## 12. Timeouts & Polling

| Couche | Endpoint | Timeout | Description |
|--------|----------|---------|-------------|
| 🔵 Frontend (sendMessage) | POST /agent/swarm/queue | aucun (réseau) | Envoi initial |
| 🔵 Frontend (sendMessage) | GET /api/task/{id}/status | **AbortSignal 10s** par requête de polling | 
| 🔵 Frontend (sendMessage) | setTimeout polling | **120s** | Arrêt du polling si backend ne répond pas |
| 🔵 Frontend (triggerVision) | setTimeout polling | **120s** | Idem pour vision |
| 🔵 Frontend (PollingUX v2.4) | GET /api/task/{id}/status | **AbortSignal 120s** | Fallback polling silencieux |
| 🟢 Backend (_call_utu) | `asyncio.wait_for` | **300s** | Timeout de génération LLM (gemma4 + qwen3) |
| 🟢 Backend (vision) | `httpx.AsyncClient` | **180s** | Capture écran + description |
| 🟢 Backend (swap_model) | `subprocess.run` | 30s bloquant | Sera refactorisé en v0.9.0 avec `asyncio.to_thread` |

**Problème résolu v0.8.1 :**
- `pollStatus()` n'affiche plus d'erreurs dans le chat (→ `console.debug`)
- Le vrai timeout est géré uniquement par `sendMessage()`
- Le backend ne tue plus les générations longues (300s au lieu de 60s)

---
*Documentation v0.8.1 — Juin 2026*

---

## 4. Dreaming V3 — Pipeline Mémoriel

### Concept

Le DevKit intègre désormais un **cycle de rêve** qui transforme les logs bruts en mémoire structurée :

```
Logs bruts → [Rêveur] → state_memoire.json → [Injecteur] → Prompt système
                 ↑                                    |
              (cron 4h)                          Sliding Window (10 derniers échanges)
```

### Commandes rapides

```bash
# Lancer le rêve (consolidation manuelle)
cd /home/realia/realia-docker/dock-rias-rp
python3 dream_pipeline.py

# Voir la mémoire actuelle
cat state_memoire.json

# Forcer un rêve avec logs des 3 derniers jours
python3 dream_pipeline.py --days 3

# Logs de l'exécution automatique (cron)
tail -f logs/dream_cron.log
```

### Fichiers de l'écosystème Dreaming

| Fichier | Description |
|---------|-------------|
| `dream_pipeline.py` | Script de consolidation (Rêveur) |
| `cron_dreaming.sh` | Wrapper bash pour cron (4h) |
| `state_memoire.json` | Mémoire consolidée |
| `logs/YYYY-MM-DD.jsonl` | Logs d'interactions brutes |
| `logs/dream_cron.log` | Logs d'exécution du rêve |

### Architecture du prompt (ordre d'injection)

1. **Mémoire long terme** (`load_state_memoire`) — stack, projets, préférences
2. **Mémoire court terme** (`_format_sliding_window`) — 10 derniers messages
3. **Inner Monologue** (`[PROTOCOLE DE RÉFLEXION OBLIGATOIRE]`) — directive <thinking>
4. **Prompt original** — la demande de l'utilisateur
5. **Outils** (`_format_tool_schemas`) — ToolRegistry
6. **Auto-Correction** (boucle) — jusqu'à 3 retries sur erreur détectée

## v2.1-contrat — Optimisation Inférence & UI (Juin 2026)

### Changements techniques
- **Threads CPU** : `--threads 8` → `--threads 12` (exploitation 24 cœurs)
- **Dream Pipeline** : Modèle de rêve passé de `gemma4-e4b` à `qwen3.6-35b`
- **Flush Sliding Window** : Nouveau mécanisme → `flush_sliding_window_to_logs()` vide le buffer RAM dans `logs/YYYY-MM-DD.jsonl` après chaque cycle contrat
- **Parsing JSON blindé** : `parse_json_response()` nettoie les balises markdown avant `json.loads()`

### UI Violette — Optimisations
1. **Swarm Monitor animé** : Pulsation néon `.agent-active` + indicateur swap/cache
2. **Terminal bash** : Logs colorés (vert néon pour `[SORTIE BASH]`, rouge pour `[ERREUR]`)
3. **Toasts FAILED** : Notifications rouges quand le contrat échoue
4. **Fond hexagonal** : Grille subtile `#161233` sur fond `#0a0813`

### URLs dynamiques
Tous les appels API JS utilisent désormais :
```js
window.REALIA_CONFIG?.API_BASE || window.API_BASE || 'http://localhost:8095'
```
Plus aucun hardcodage brut dans `action-router.js`, `editor-optim.js`, `ws-monitor.js`, `panel-lazy-loader.js`, `split-view.js`.

### Endpoints obsolètes supprimés
- `/system/model/load` — supprimé (swap automatique par ModelSwapper)
- `/system/model/unload` — supprimé (swap automatique par ModelSwapper)
