# Changelog
All notable changes to RealiaDevKit will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-07-01

### Added

- **PlanExecutor v1.0.0** — Module d'exécution de plans multi-étapes
- 4 contrats formels (schema, state machine, validation, erreurs) — 96 KB
- 30 edge cases identifiés et traités
- 8 exceptions hiérarchiques (PlanExecutorError + 7 sous-classes)
- 5 couches de Defense in Depth
- 47 tests unitaires (89% coverage)
- **sandbox.py** — Module d'isolation et sécurité pour écriture fichiers
- 4 fonctions publiques (check_sandbox, is_safe_path, create_backup, sandbox_write)
- 6 tests unitaires
- Extrait de devkit_orchestrator.py (prépare modularisation)

### Changed

- **Refactoring constantes nommées** — Élimination de 26 hardcodages
- 9 constantes ajoutées (PLANNER_MODEL, EXECUTOR_MODEL, LLM_TIMEOUT_SECONDS, etc.)
- 11 noms de modèles remplacés
- 15 magic numbers remplacés
- **Architecture exceptions hiérarchique** — PlanExecutorError comme base
- Toutes les erreurs héritent de PlanExecutorError
- Single catch-all : `except PlanExecutorError`

### Fixed

- **PlanExecutorError import manquant** — Bug critique découvert par tests
- Les blocs `except PlanExecutorError` (l.548, 559) ne fonctionnaient pas
- Ajouté dans les imports (l.19)
- Sans ce fix, la boucle retry (Principe 5) aurait crashé en production
- **13 edge cases corrigés** sur 30 identifiés
- EC-01 (plan vide), EC-02 (cycle), EC-03 (doublons)
- EC-04 (instruction vide), EC-07 (timeout LLM)
- EC-13 (modèle inconnu), EC-15 (fallback modèle)
- EC-17 (cache restore fail), EC-18 (swap fail)
- EC-19 (concurrent execution), EC-24 (swap fallback chain)
- EC-28 (race condition), EC-30 (output truncation)

### Security

- **Sandbox isolation** — Principe 4 du Genesis Protocol respecté
- PlanExecutor utilise maintenant `sandbox_write()` au lieu de `Path.write_text()`
- Validation chemin dans SANDBOX = BASE_DIR
- Backup automatique .bak.realia avant écriture

### Documentation

- **README_plan_executor.md** — 219 lignes
- Description des 4 contrats
- 9 états de la state machine
- 12 transitions documentées
- 8 invariants
- **Docstrings** — Complétées pour toutes les fonctions publiques

### Testing

- **47 tests unitaires** — 89% coverage global
- 16 tests MemorySystem
- 17 tests PlanExecutor (lots 1-4)
- 6 tests sandbox
- 8 tests exceptions
- **Tests critiques couverts** :
- validate_step (53 lignes, 92% coverage)
- Boucle retry (26 lignes, 100% coverage)
- Branche next_step (23 lignes, 96% coverage)

## [0.9.4] - 2026-06-28

### Added

- MemorySystem v1.0.0 — 3 tiers (KV-cache, sliding window, long-term)
- SelfCorrection v1.0.0 — 3 retries, 16+ patterns
- 43 tests unitaires pour SelfCorrection

### Changed

- RealiaDevKit v0.9.4 — 30 edge cases traités

[Previous versions omitted for brevity]
