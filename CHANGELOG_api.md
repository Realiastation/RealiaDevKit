# Changelog — API Contract v1.0.0

## [1.0.0] - 2026-07-01

### Added
- WebSocket endpoint `/ws/task/{task_id}` sur port 8092 (FastAPI)
- 4 événements temps réel : `task_started`, `task_progress`, `task_completed`, `task_failed`
- Feature flags dynamiques (`USE_WEBSOCKET`, `WS_PORT`, etc.)
- ConnectionManager avec broadcast par channel
- 7 fichiers de test unitaires (couverture >85%)
- Endpoint `GET /config/feature-flags` pour configuration frontend

### Changed
- `devkit_orchestrator.py` : intégration router WS + événements dans swarm_worker
- `plan_executor.py` : émission `task_progress` pendant boucle d'exécution

### Security
- Zéro breaking change (16 endpoints REST conservés)
- Feature flag `USE_WEBSOCKET=false` par défaut (opt-in)

### Genesis Protocol
- Principe 6 : local only (pas d'authentification, pas de cloud)
- Principe 5 : self-correction (broadcaster émet même si erreur)
