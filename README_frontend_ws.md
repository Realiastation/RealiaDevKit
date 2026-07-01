# Connexion WebSocket Frontend — RealiaDevKit

## Activation

WebSocket est désactivé par défaut. Pour l'activer :

```bash
export USE_WEBSOCKET=true
# Puis redémarrer le backend
./start_devkit.sh
```

Le feature flag est détecté automatiquement par le frontend via `GET /config/feature-flags`.

## Architecture

```
[Frontend] ←→ WebSocket (port 8092) ←→ Backend DevKit
                ↓ (si échec)
           [Fallback Polling] (1.5s, REST /api/task/{id}/status)
```

## Événements WebSocket

| Événement         | Données                          | Déclencheur             |
|-------------------|----------------------------------|-------------------------|
| `task_started`    | `{ task_id }`                    | Début de tâche          |
| `task_progress`   | `{ progress_pct, step_name, step_index, step_total }` | Mise à jour étape |
| `task_completed`  | `{ task_id, result }`            | Fin de tâche réussie    |
| `task_failed`     | `{ task_id, error }`             | Échec de tâche          |

## Tests manuels

### 1. Activer WebSocket

```bash
USE_WEBSOCKET=true python devkit_orchestrator.py
```

### 2. Vérifier le feature flag

```bash
curl http://localhost:8095/config/feature-flags
# Attendu : {"USE_WEBSOCKET":true,"WS_PORT":8092,...}
```

### 3. Lancer une tâche

Ouvrir `http://localhost:8095/` dans le navigateur.

1. Taper un message dans le chat et envoyer
2. Observer la barre de progression et les informations d'étape
3. Vérifier que l'indicateur WebSocket dans la barre d'outils passe au vert

### 4. Tester le fallback

1. Arrêter le backend (`Ctrl+C`)
2. Vérifier que le frontend bascule automatiquement sur le polling REST
3. Redémarrer le backend : le fallback reste actif pour la tâche en cours
4. Les nouvelles tâches retenteront le WebSocket

### 5. Tester la reconnexion

1. Avec le backend actif, lancer une tâche
2. Observer la connexion WS établie (icône verte)
3. Redémarrer le backend : le client tente la reconnexion 5 fois (1s, 2s, 4s, 8s, 16s)
4. Après 5 échecs, le fallback polling est activé automatiquement

## Dépannage

| Symptôme                          | Cause probable                | Solution                          |
|-----------------------------------|-------------------------------|-----------------------------------|
| WebSocket reste rouge             | `USE_WEBSOCKET=false`         | Activer le flag et redémarrer     |
| Connexion refusée                 | Port 8092 non ouvert          | Vérifier `devkit_config.json`     |
| Fallback polling activé           | WS down > 5 tentatives        | Redémarrer backend pour réessayer |
| Messages non reçus                | Proxy/CORS bloque WS          | Vérifier les en-têtes CORS        |

## Code source

- `js/websocket-client.js` — Classe `RealiaWebSocketClient` (connexion, reconnexion, fallback)
- `realia_dev_gui.html` — Intégration (script, helpers, remplacement polling)
