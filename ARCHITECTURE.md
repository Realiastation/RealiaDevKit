# 🏗️ Architecture Swarm DevKit (RTX 4080 16GB Optimized)

> **RÉSUMÉ DevSenior** — *À lire en priorité si perte de mémoire.*
> 
> **Un seul modèle à la fois dans la VRAM (16 Go).**
> Le système alterne entre Gemma4 (4B, full GPU, ctx 16384) et Q3N 80B (MoE, 35 layers GPU, ctx 8192)
> via **kill + restart** du processus llama-server. Pas de coexistence. Pas de routeur parallèle.
> 
> Le swap est géré par la classe `ModelSwapper` dans `devkit_orchestrator.py` :
> 1. `save_slot()` → persiste le KV Cache avant le kill
> 2. `proc.terminate()` + `wait(10)` → libère 100 % VRAM via CUDA
> 3. `time.sleep(1)` → attend libération du port 9094
> 4. `subprocess.Popen()` → relance avec les flags du nouveau modèle (`--mmap` → 1-3 s, pas 30+ s)
> 5. `restore_slot()` → restaure le KV Cache
> 
> **Fichiers clés :**
> - `start_server.sh` → démarre Gemma4 par défaut (ne pas modifier les flags)
> - `devkit_orchestrator.py` → `ModelSwapper` (swap), `SwarmRouter` (routage)
> - `cache_roaming.py` → `CacheRoaming` (save/restore des slots) — **NE PAS TOUCHER**
> - `archive_skill.py` → Skill partagé de filtrage/condensation des logs JSONL
> - `dream_pipeline.py` → Rêveur nocturne : consolidation mémoire → `state_memoire.json` (t=0.1)
> 
> **Pour ajouter un modèle :** 6 points de modification (voir audit ci-dessous)

## 🎯 Philosophie et Contraintes Matérielles

Ce système est conçu pour faire cohabiter un routeur rapide (Gemma4 4B) et un exécuteur massif (Qwen3-Coder-Next ~85B MoE) sur une seule GPU de 16 Go.

**Contrainte absolue :** La fenêtre de contexte (CW) doit rester exploitable. Il est **INTERDIT** de charger les deux modèles simultanément en VRAM, car cela saturerait la mémoire (4-5 Go + 4-5 Go + KV Cache > 16 Go) et réduirait la CW à néant, rendant le système inutilisable pour des tâches complexes.

## ⚙️ Mécanisme de Swap Séquentiel (Le Cœur du Système)

Contrairement aux serveurs cloud multi-utilisateurs, nous utilisons un swap séquentiel optimisé par le système d'exploitation, géré par la classe `ModelSwapper` dans `devkit_orchestrator.py` :

1. **Sauvegarde du contexte :** `cache_roaming.save_slot()` persiste l'état du KV Cache en RAM avant toute modification.
2. **Libération totale de la VRAM :** `proc.terminate()` + `wait(10)`. Le driver CUDA libère *immédiatement et totalement* la VRAM de l'ancien modèle.
3. **Pause de libération :** `time.sleep(1)` pour garantir que le port 9094 est libéré par l'OS.
4. **Chargement Rapide (mmap) :** `subprocess.Popen` relance `llama-server` avec les flags spécifiques du modèle. Grâce au flag `--mmap`, le fichier GGUF (déjà dans le page cache Linux du swap précédent) est rechargé en 1 à 3 secondes, et non 30+ secondes. Aucune lecture disque physique n'a lieu.
5. **Restauration du contexte :** `cache_roaming.restore_slot()` réinjecte l'état du KV Cache. Pour l'utilisateur, le contexte est préservé de manière transparente.

## 📋 Configuration Stricte des Modèles (NE PAS MODIFIER SANS VALIDATION)

### Gemma4-E4B (Routeur)

- `n-gpu-layers = 99` (Tout le modèle en VRAM, ~4-5 Go)
- `ctx-size = 16384` (Nécessite la VRAM entièrement libérée par l'absence de Q3N)
- `flash-attn = on`, `mmproj = mmproj-F16.gguf`

### Qwen3-Coder-Next (Exécuteur MoE ~85B)

- `n-gpu-layers = 35` (Seules les couches d'attention/embedding en VRAM, ~4-5 Go)
- `cpu-moe = true` (Les ~80 Go de poids des experts restent en RAM système)
- `mlock = true` (Verrouille les poids en RAM physique, interdit le swap OS sur SSD)
- `ctx-size = 8192`
- `flash-attn = on`

## ⚠️ AVERTISSEMENTS CRITIQUES POUR LES DÉVELOPPEURS FUTURS

- 🚫 **NE PAS** activer le mode routeur parallèle (`--models-dir`, `--models-preset`, `POST /models/load`). Il chargerait les deux modèles en VRAM simultanément, saturant les 16 Go et détruisant la fenêtre de contexte.
- 🚫 **NE PAS** supprimer `--mmap` ou `--mlock`. Sans eux, le temps de swap passerait de ~2s à ~45s (lecture disque physique) et le système deviendrait instable (OOM).
- 🚫 **NE PAS** réduire le `timeout=10` du `proc.wait()`. Ce délai est nécessaire pour que le driver CUDA libère proprement la mémoire avant le prochain `Popen`.

## 🔄 Flux d'exécution dans `_call_utu`

1. `save_slot(ancien modèle)` → persiste le contexte
2. `swapper.swap(nouveau)` → kill + restart (libération VRAM)
3. `restore_slot(nouveau)` → restaure le contexte
4. Inférence LLM...
5. `save_slot(nouveau)` → sauvegarde pour le prochain tour
