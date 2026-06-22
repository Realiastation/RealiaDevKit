# DEVKIT v0.9.3 — STATUS

## Etat actuel (2026-06-13)

**Backend** : port 8095, FastAPI, Swap Séquentiel + Tools & Skills Layer
**LLM** : port 9094, llama-server swap séquentiel (kill + restart, un seul modèle à la fois)
**Gemma4** : Routeur, full GPU (ngl=99), multimodal (mmproj), ctx 16384, ~4.9 Go VRAM
**Qwen3-Coder-Next** : Exécuteur MoE 80B, cpu-moe, ngl=35, ctx 8192, mlock

**Swap** : `ModelSwapper.swap()` dans `devkit_orchestrator.py` — terminate() + wait(10) + Popen()
**Cache KV** : `cache_roaming.py` via POST /slots/{id}?action=save|restore — **NE PAS MODIFIER**

## Skills & Pipelines

### archive_skill.py (NEUF v0.9.3)
Skill partagé pour le duo G4/Q3N — filtre et condense les logs JSONL :
- `prepare_archive_chunk(log_path, max_chars=8000)` → `[HH:MM] agent -> rôle: contenu (500 car.)`
- Filtre le bruit système : boilerplate, protocoles, contextes mémoire
- Troncature propre à 8000 caractères max avec marqueur

### dream_pipeline.py (Archiviste Système)
Rêveur nocturne — consolidation mémoire dans `state_memoire.json` :
- Utilise `archive_skill` pour condenser les logs avant appel API
- Prompt "Archiviste Système" : fusion fidèle, concision absolue
- Température forcée à **0.1** (zéro hallucination)
- Appelable via CLI : `python3 dream_pipeline.py --days 1`
- Cron : `cron_dreaming.sh` (planifié la nuit)

## Fichiers actifs

| Fichier | Role | Lignes |
|---------|------|--------|
| devkit_orchestrator.py | Backend API (FastAPI) | ~850 |
| cache_roaming.py | API REST des slots KV (NE PAS MODIFIER) | ~350 |
| archive_skill.py | Skill d'archivage des logs (NEUF) | ~150 |
| dream_pipeline.py | Rêveur nocturne mémoire (t=0.1) | ~240 |
| tools_registry.py | Registre d'outils sandbox | 152 |
| start_server.sh | Démarrage llama-server (Gemma4 par défaut) | ~130 |
| emergency_restart.sh | Fallback kill + restart forcé | ~100 |
| cron_dreaming.sh | Cron du rêveur nocturne | ~40 |
| state_memoire.json | Mémoire persistante de l'utilisateur | variable |
| ARCHITECTURE.md | Documentation architecture (LIRE AVANT TOUTE MODIF) | ~80 |
| RUNBOOK.md | Documentation opérateur | - |
| DEVKIT_STATUS.md | Ce fichier | - |

## Architecture du swap

```
_call_utu (devkit_orchestrator.py):
  1. save_slot(ancien modèle)  → persiste le KV Cache
  2. swapper.swap(nouveau)     → kill + restart (libère 100% VRAM)
  3. restore_slot(nouveau)     → restaure le contexte
  4. Inférence LLM...
  5. save_slot(nouveau)        → sauvegarde pour prochain tour
```

## Commandes utiles

```bash
# Demarrage
python3 devkit_orchestrator.py

# Test rapide
curl -s -X POST :8095/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"gemma4","messages":[{"role":"user","content":"Dis bonjour"}],"max_tokens":30}'

# Voir les logs Tool Loop
grep TOOL_ devkit.log

# Charger Qwen3
curl -X POST :8095/models/load -H "Content-Type: application/json" -d '{"model":"qwen3-coder"}'
```

---

*Documentation v0.9.2 — 05/06/2026*

---

## Architecture Cognitive v0.9.5+ — Dreaming V3

### Vue d'ensemble

```
┌─ Journalier (log_interaction) ──────────────────────┐
│ Écrit chaque échange dans logs/YYYY-MM-DD.jsonl      │
│ Format: timestamp, agent, role, content              │
└─────────────────────────┬─────────────────────────────┘
                          ↓
┌─ Rêveur (dream_pipeline.py) ─────────────────────────┐
│ python3 dream_pipeline.py [--days N] [--dry-run]     │
│ Consolidation asynchrone via Gemma4 (port 9094)      │
│ Fusionne les logs → state_memoire.json               │
└─────────────────────────┬─────────────────────────────┘
                          ↓
┌─ Injecteur (load_state_memoire) ──────────────────────┐
│ Lit state_memoire.json → bloc texte lisible           │
│ Injecté en tête de chaque prompt _call_utu()          │
│ Contient : stack, projets, préférences, directive     │
└─────────────────────────┬─────────────────────────────┘
                          ↓
┌─ Sliding Window (conversation_history) ───────────────┐
│ Buffer par agent (Q3N ≠ G4), 10 messages max         │
│ Injecté entre mémoire long terme et prompt actuel     │
└─────────────────────────┬─────────────────────────────┘
                          ↓
┌─ Auto-Correction (Self-Correction) ────────────────────┐
│ Détection de 16 patterns d'erreur (Traceback, etc.)  │
│ Jusqu'à 3 retries avec [OBSERVATION_OUTIL]            │
│ + Directive [DIRECTIVE D'AUTO-CORRECTION]             │
└─────────────────────────┬─────────────────────────────┘
                          ↓
┌─ Inner Monologue (Réflexion Pré-Action) ──────────────┐
│ [PROTOCOLE DE RÉFLEXION OBLIGATOIRE]                  │
│ <thinking> obligatoire avant chaque outil             │
│ Balises nettoyées de la sortie utilisateur            │
└───────────────────────────────────────────────────────┘
```

### Composants détaillés

#### 1. Journalier — `log_interaction(agent_name, role, content)`
- Écriture synchrone dans `logs/YYYY-MM-DD.jsonl`
- Appelée **avant** l'appel UTU (role: user) et **après** (role: assistant)
- Troncature à 2000 caractères pour limiter la taille des logs

#### 2. Rêveur — `dream_pipeline.py` (script autonome)
- Exécution standalone : `python3 dream_pipeline.py`
- Flags : `--days N` (défaut: 1), `--dry-run` (debug sans API)
- Automatisation cron : tous les jours à 4h via `cron_dreaming.sh`
- Logs dans `logs/dream_cron.log`

#### 3. Injecteur mémoire long terme — `load_state_memoire()`
- Lit `state_memoire.json` (créé automatiquement si absent)
- Formate en bloc lisible : stack technique, projets, préférences
- **Silencieux** : retourne `""` si fichier absent → pas de crash

#### 4. Sliding Window — `conversation_history[agent_name]`
- Buffer isolé par agent (realia_dev ≠ realia_coder)
- 10 messages max (5 échanges utilisateur ↔ assistant)
- Format : `[CONTEXTE RÉCENT - SLIDING WINDOW]`

#### 5. Auto-Correction — Boucle d'apprentissage active
- `_detect_error_in_output()` : détecte 16 patterns (SyntaxError, FileNotFound, etc.)
- `_format_observation()` : formate `[OBSERVATION_OUTIL]`
- `_inject_observation()` : injecte l'erreur dans le sliding window
- Jusqu'à `SELF_CORRECT_MAX_RETRIES = 3` tentatives
- Directive système : `[DIRECTIVE D'AUTO-CORRECTION]`

#### 6. Inner Monologue — Réflexion Pré-Action
- `[PROTOCOLE DE RÉFLEXION OBLIGATOIRE]`
- Balise `<thinking>` obligatoire avant chaque outil
- Nettoyée de la sortie utilisateur via `re.sub(r'<thinking>.*?</thinking>', ...)`

### Ordre final du prompt

```
[CONTEXTE UTILISATEUR SYNTHÉTISÉ - DREAMING V3]   ← Mémoire long terme
---
[CONTEXTE RÉCENT - SLIDING WINDOW]                 ← Mémoire court terme
Utilisateur: ...
Assistant: ...
---
[PROTOCOLE DE RÉFLEXION OBLIGATOIRE]               ← Inner Monologue
---
{prompt_original}                                   ← Demande actuelle
---
{Outils externes disponibles}                       ← ToolRegistry
```

### Commandes utiles

```bash
# Lancer le rêve manuellement (consolidation des logs du jour)
python3 dream_pipeline.py

# Rêve sur les 3 derniers jours
python3 dream_pipeline.py --days 3

# Aperçu du prompt sans appeler l'API
python3 dream_pipeline.py --dry-run

# Voir les logs de rêve
cat logs/dream_cron.log

# Voir les logs d'interactions brutes
cat logs/$(date +%Y-%m-%d).jsonl

# Voir la mémoire consolidée
cat state_memoire.json
```

### Fichiers créés

| Fichier | Rôle |
|---------|------|
| `dock-rias-rp/dream_pipeline.py` | Pipeline de consolidation mémorielle |
| `dock-rias-rp/cron_dreaming.sh` | Script wrapper cron (4h quotidien) |
| `dock-rias-rp/state_memoire.json` | Mémoire consolidée (générée auto) |
| `dock-rias-rp/logs/YYYY-MM-DD.jsonl` | Logs d'interactions brutes (Journalier) |
| `dock-rias-rp/logs/dream_cron.log` | Logs d'exécution du rêve programmé |

---

*Documentation v0.9.5+ — Dreaming V3 intégré*

## Optimisation Juin 2026 — v2.1-contrat Sprint 2

### Bilan des 3 chantiers fermés

| Chantier | Statut | Détail |
|---|---|---|
| Threads CPU 8→12 | ✅ | Exploitation 24 cœurs CPU pour inference MoE |
| Hardcodé URL éradiqué | ✅ | 5 fichiers JS passés au pattern résilient |
| Endpoints obsolètes nettoyés | ✅ | `/system/model/load` et `/system/model/unload` retirés |
| Flush sliding window → logs | ✅ | `flush_sliding_window_to_logs()` avant chaque finalisation contrat |
| Dream Pipeline → Qwen3.6 | ✅ | `MODEL_NAME = "qwen3.6-35b"` + prompt priorise `sliding_window_flush` |
| Parsing JSON blindé | ✅ | Étape 0 : nettoyage markdown avant `json.loads()` |
| UI Swarm animée | ✅ | Pulsation néon `.agent-active` + indicateur swap |
| Terminal bash coloré | ✅ | Logs avec vert néon pour SORTIE BASH, rouge pour ERREUR |
| Toasts FAILED | ✅ | Notification automatique sur échec contrat |
| Fond hexagonal station | ✅ | Grille subtile `#161233` sur `#0a0813` |
