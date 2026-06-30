# 📜 PlanExecutor — Contrat d'Interface v1.0.0

## Identité du Contrat

| Propriété | Valeur |
|---|---|
| **Module** | `PlanExecutor` (`plan_executor.py`) |
| **Version** | `v1.0.0` |
| **Date de création** | 2026-06-29 |
| **Statut** | ✅ Ratifié |
| **Principe** | 🔒 Immuable — toute modification nécessite le **Genesis Protocol** |

## Structure du Contrat

Ce contrat est divisé en **4 parties** indépendantes mais liées :

| Partie | Fichier | Objet | Statut |
|---|---|---|---|
| **Partie 1** | `plan_executor_contract_part1_schema.json` | Schémas JSON (entrée, plan, sortie) | ✅ Ratifié |
| **Partie 2** | `plan_executor_contract_part2_statemachine.json` | Comportement de la state machine (états, transitions, boucles) | ✅ Ratifié |
| **Partie 3** | `plan_executor_contract_part3_validation.json` | Règles de validation (seuils, critères de passage) | ✅ Ratifié |
| **Partie 4** | `plan_executor_contract_part4_errors.json` | Gestion des erreurs et cas limites | ✅ Ratifié |

## Partie 1 — Schémas JSON

Le fichier `plan_executor_contract_part1_schema.json` définit **3 schémas** conformes à JSON Schema draft-07 :

### 1. `PlanExecutorInput`
Entrée du PlanExecutor. Propriétés :
- **`task`** *(string, requis)* : Description textuelle de la tâche
- **`context`** *(object, optionnel)* : Contexte avec propriétés libres (`additionalProperties: true`)

### 2. `Plan`
Liste ordonnée de 1 à 5 étapes. Chaque étape a :
- **`step`** *(number)* : Numéro d'étape (peut être fractionnaire)
- **`action`** *(enum)* : `code`, `chat`, ou `reason`
- **`model`** *(enum)* : `qwen3.6-35b`, `qwen3-coder-next`, ou `gemma4-12b`
- **`instruction`** *(string)* : Instruction autosuffisante
- **`success_criteria`** *(string, optionnel)* : Critère de validation
- **`depends_on`** *(array[number], optionnel)* : Dépendances

### 3. `PlanExecutionResult`
Résultat global de l'exécution :
- **`success`** *(boolean)* : Toutes les étapes réussies ?
- **`final_output`** *(string)* : Résumé textuel final
- **`plan`** *(array)* : Plan exécuté
- **`step_results`** *(object)* : Résultats par étape (clés = string(step_num))
- **`loops`** *(integer)* : Nombre total de retries
- **`time_elapsed_s`** *(number)* : Temps d'exécution en secondes
- **`status`** *(enum)* : `success`, `partial`, ou `failed`


## Partie 2 — State Machine

Le fichier `plan_executor_contract_part2_statemachine.json` définit le **contrat de comportement** du PlanExecutor.

### États (9)

```
INIT -> PLAN -> EXECUTE -> VALIDATE -> NEXT_STEP -> (loop)
                                    |
                               LOOP -> VALIDATE (retry)
                                    |
                          EXECUTE_NEXT_STEP -> VALIDATE (step+0.5)
```

| État | Description | Transitions |
|---|---|---|
| `INIT` | Initialisation, reset des compteurs | -> PLAN |
| `PLAN` | Génération du plan par Gemma4-12B | -> EXECUTE / FAILED |
| `EXECUTE` | Exécution d'une étape (swap VRAM + inference) | -> VALIDATE |
| `VALIDATE` | Validation via Gemma4-12B | -> NEXT_STEP / LOOP / EXECUTE_NEXT_STEP |
| `LOOP` | Retry avec feedback de correction | -> VALIDATE / FAILED |
| `EXECUTE_NEXT_STEP` | Étape intermédiaire (step + 0.5) | -> VALIDATE |
| `NEXT_STEP` | Passage à l'étape suivante | -> EXECUTE / TERMINATE |
| `TERMINATE` | Succès : résumé final + retour | -> [*] |
| `FAILED` | Échec partiel ou total | -> [*] |

### Invariants Globaux (8)

| ID | Règle | Critique |
|---|---|---|
| GI-1 | Un seul modèle en VRAM à la fois | 🔴 Oui |
| GI-2 | Max 3 retries par étape (Genesis rule_3) | 🔴 Oui |
| GI-3 | Contexte étapes précédentes limité à 300 car. | ⚪ Non |
| GI-4 | Contenu fichier limité à 3000 car. | ⚪ Non |
| GI-5 | Backup .bak.realia avant écriture fichier | 🔴 Oui |
| GI-6 | Cache KV N1+N2 partagé entre étapes | ⚪ Non |
| GI-7 | Plan limité à 5 étapes | ⚪ Non |
| GI-8 | Dépendances non bloquantes | ⚪ Non |

### Conditions de Sortie

- **success** : toutes les étapes passées
- **partial** : certaines étapes réussies, d'autres non
- **failed** : échec critique ou max retries atteint


## Partie 3 — Règles de Validation

Le fichier `plan_executor_contract_part3_validation.json` définit les **règles de validation** de toutes les transitions de la state machine.

### Stratégie de sélection du validateur

**Principe :** Validation distribuée avec *competence-based routing*. Aucun modèle n'est hardcodé comme unique validateur.

| Type d'étape | Validateur préféré | Fallbacks |
|---|---|---|
| `code` | qwen3-coder-next | gemma4-12b → qwen3.6-35b |
| `chat` | gemma4-12b | qwen3.6-35b |
| `reason` | gemma4-12b | qwen3.6-35b → qwen3-coder-next |

**Contrainte :** Le validateur doit être différent du modèle exécuteur si possible (éviter l'auto-validation biaisée).

### Types de validation (9 transitions)

| Transition | Type | Règles |
|---|---|---|
| PLAN → EXECUTE | Déterministe | 6 règles (V-PLAN-1 à 6) : JSON valide, array, non vide, schema, modèle, max 5 étapes |
| EXECUTE → VALIDATE | Hybride | 3 règles (V-EXEC-1 à 3) : checks déterministes selon action, swap, backup |
| VALIDATE → NEXT_STEP | Stochastique | 2 règles (V-VAL-1 à 2) : LLM pass ou court-circuit chat |
| VALIDATE → LOOP | Stochastique | 3 règles (V-VAL-3 à 5) : fail avec feedback, attempt ≤ 3, suggested_fix |
| VALIDATE → EXECUTE_NEXT_STEP | Stochastique | 2 règles (V-VAL-6 à 7) : next avec instruction, step numbering |
| LOOP → VALIDATE | Hybride | 3 règles (V-LOOP-1 à 3) : fix injecté, retry exécuté, loop_count incrémenté |
| LOOP → FAILED | Déterministe | 2 règles (V-LOOP-4 à 5) : attempt > 3, step toujours failed |
| NEXT_STEP → EXECUTE | Déterministe | 2 règles (V-NEXT-1 à 2) : index valide, dépendances |
| NEXT_STEP → TERMINATE | Déterministe | 2 règles (V-NEXT-3 à 4) : toutes les étapes traitées, résultats complets |

### Règles de retry

- **Max retries :** 3 par étape (Genesis rule_3)
- **Condition :** `validation.status == 'fail'`
- **Action :** Injection du `suggested_fix` dans l'instruction
- **Abandon :** `attempt > 3` → transition vers FAILED

### Court-circuit chat

Si l'action est `chat` et l'output non vide, la validation LLM est court-circuitée (validation implicite pass).

## Partie 4 — Gestion des Erreurs et Cas Limites

Le fichier `plan_executor_contract_part4_errors.json` définit la **gestion exhaustive des erreurs** : 30 edge cases documentés, 24 entrées dans la matrice erreur→recovery.

### Catégories d'erreur (5)

| Catégorie | Séverité | Exemples | Stratégies |
|---|---|---|---|
| Infrastructure | Critique | VRAM full, disque plein, process crash, permission | backoff, graceful, abort |
| Modèle | Haute | JSON invalide, hallucination, timeout, output vide | feedback, fallback, parsing |
| Logique | Haute | Plan invalide, dépendance circulaire, step sans instruction | regen, abort, skip |
| Validation | Moyenne | Code incorrect, erreur syntaxe, parsing fail | feedback, abort |
| Système | Critique | Boucle infinie, deadlock, mémoire, exécution concurrente | hard_abort, state_persistence |

### Stratégies de recovery (10)

| Stratégie | Description | Applicable à |
|---|---|---|
| `retry_with_backoff` | Attente exponentielle (1s→30s) | Infrastructure |
| `retry_with_feedback` | Injection du suggested_fix | Modèle, Validation |
| `fallback_model` | Utiliser un modèle de secours | Modèle |
| `graceful_degradation` | Continuer sans l'étape problématique | Infrastructure, Logique |
| `abort_with_feedback` | Arrêter avec message explicatif | Toutes sauf Système |
| `regenerate_plan` | Regénérer le plan avec feedback | Logique |
| `parsing_fallback` | Heuristique mots-clés pour JSON invalide | Modèle |
| `hard_abort` | Arrêt d'urgence avec sauvegarde d'état | Système |
| `skip_step` | Passer une étape non critique | Logique |
| `state_persistence` | Snapshot périodique pour reprise après crash | Système |

### Edge cases (30)

- **13 nécessitent un fix** (🔧) : plan vide, instruction manquante, dépendance circulaire, swap échoue, timeout LLM, step sans file_path, modèle inexistant, duplicate steps, Agent creation fail, cache fail, swap échoue pour code, exécution concurrente, output tronqué
- **17 déjà OK** (✅) : backup, max loops, troncature, parsing fallback, next sans instruction, etc.

### Timeouts (4)

| Opération | Timeout | On timeout |
|---|---|---|
| Inférence LLM | 60s | retry_with_backoff → fallback_model |
| Génération plan | 120s | fallback minimal → abort |
| Validation | 60s | consider_as_fail → abort |
| Cache KV | 5s | continue_without_cache |

### Matrice erreur→recovery (24 entrées)

Chaque erreur possible est mappée à sa stratégie de recovery primaire et son fallback, avec la localisation dans le code et le pattern de log associé.

## Principe d'Immuabilité

Ce contrat est **immuable** une fois ratifié. Toute modification doit passer par le **Genesis Protocol** :

1. **Signalement** : Ouvrir une issue ou un audit avec la modification proposée
2. **Validation** : L'architecte (Gemma4) valide l'impact sur les autres parties
3. **Versioning** : La version mineure est incrémentée (`v1.0.0` → `v1.1.0`) pour les ajouts non-cassants, la version majeure (`v2.0.0`) pour les changements cassants
4. **Ratification** : Toutes les parties sont mises à jour et re-ratifiées

## Notes Techniques

### Modèles Valides
Les 3 modèles suivants sont reconnus par `config_map` dans `plan_executor.py` :
- `qwen3.6-35b` → config UTU `realia_qwen36`
- `qwen3-coder-next` → config UTU `realia_coder`
- `gemma4-12b` → config UTU `realia_g4_12b`

Tout autre nom de modèle sera résolu en fallback `realia_dev`.

### Discrepances Connues (v1.0.0)
Ces différences entre le contrat et l'implémentation actuelle seront résolues dans les versions futures :
- Le champ `status` retourne actuellement `"completed"` / `"completed_with_errors"` au lieu de `"success"` / `"partial"` / `"failed"`
- Le champ `step` dans les plans utilise l'ancien nom `step_num` dans certains contextes
- `qwen3.6-35b` est actuellement absent du planner_template (utilisé uniquement comme fallback dans `execute_step`)

## Références

- **Code source** : `dock-rias-rp/plan_executor.py`
- **Générateur de plan** : `dock-rias-rp/planner_template.py`
- **Validateur** : `dock-rias-rp/validator_template.py`
- **Cache KV** : `dock-rias-rp/cache_roaming.py`
- **Tests** : `dock-rias-rp/test_memory_*.py` (16 tests)
- **Dépendances** : `utu.agents.SimpleAgent` (framework UTU), `devkit_orchestrator.swapper` (swap VRAM)


## Architecture — sandbox.py

PlanExecutor v1.0.0 utilise un module externe `sandbox.py` pour l'écriture de fichiers :

```python
from sandbox import sandbox_write
# Écriture sécurisée avec backup
sandbox_write(file_path, content)
```

**Fonctions disponibles :**

- `check_sandbox(path)` — Valide que le chemin est dans SANDBOX
- `is_safe_path(path)` — Vérifie sans lever d'exception
- `create_backup(path)` — Crée un backup .bak.realia
- `sandbox_write(path, content)` — Écrit avec validation + backup

## Tests et Coverage

**47 tests unitaires** — **89% coverage global**

| Fichier | Coverage | Tests |
|---|---|---|
| plan_executor.py | 90% | 17 tests |
| sandbox.py | 72% | 6 tests |
| plan_executor_exceptions.py | 100% | 8 tests |

**Tests critiques couverts :**

- ✅ validate_step (92% coverage)
- ✅ Boucle retry (100% coverage)
- ✅ Branche next_step (96% coverage)

## Bugs critiques corrigés

### PlanExecutorError import manquant

**Problème** : Les blocs `except PlanExecutorError` (l.548, 559) référençaient une exception non importée.

**Impact** : La boucle retry (Principe 5 — Self-Correction) aurait crashé avec `NameError` au premier échec d'exécution.

**Correction** : Ajout de `PlanExecutorError` dans les imports (l.19).

**Leçon** : Les tests unitaires révèlent les bugs invisibles. Sans les tests du Lot 2/4, ce bug serait resté caché jusqu'à la production.
