# API Contract v1.0.0 — Guide d'utilisation

## Endpoints REST (backward compatibility)
Tous les 16 endpoints REST existants sont conservés. Voir la documentation existante.

## WebSocket (NOUVEAU)

### Connexion
```javascript
const ws = new WebSocket('ws://localhost:8092/ws/task/{task_id}');
```

### Événements reçus
| Événement | Description | Data |
|---|---|---|
| `task_started` | Tâche démarrée | `{task_id, status, started_at}` |
| `task_progress` | Progression étape | `{task_id, step_index, step_total, step_name, progress_pct}` |
| `task_completed` | Tâche terminée (succès) | `{task_id, status, result, duration_s}` |
| `task_failed` | Tâche échouée | `{task_id, status, error, error_type, retry_count}` |

### Format des messages
```json
{
  "channel": "task:{task_id}",
  "event": "task_progress",
  "data": { "task_id": "...", "step_index": 1, "step_total": 5, "progress_pct": 20.0 },
  "timestamp": "2026-07-01T12:00:00Z",
  "sequence": 42
}
```

### Feature flags
Endpoint `GET /config/feature-flags` retourne la configuration WebSocket.

## Migration polling → WebSocket
- Phase 1 : WebSocket métier ajouté (port 8092) ✅
- Phase 2 : Connexion frontend (à venir)
- Phase 3 : Feature flag migration (à venir)
- Phase 4 : Suppression polling (à venir)
