# Divergence Note — API Contract v1.0.0

## Divergence 1 : Compétence-based routing non implémenté

**Contrat :** Les événements WebSocket devraient inclure des métadonnées de modèle
(quel modèle a exécuté l'étape, compétences requises).

**Implémentation :** Les événements n'incluent pas encore les métadonnées de modèle.
Le routing est fixe (config="realia_dev").

**Raison :** Le competence-based routing est prévu pour la Phase 6 (extraction SwarmKit).
L'implémentation actuelle est une simplification fonctionnelle.

**Impact :** Aucun. Le frontend reçoit la progression, les métadonnées de modèle
sont optionnelles pour la Phase 1.

## Divergence 2 : Pas d'authentification

**Contrat :** Le protocole d'authentification mentionne un handshake optionnel.

**Implémentation :** Aucune authentification (conformément au Principe 6 — local only).

**Raison :** L'environnement est local. L'authentification sera ajoutée si nécessaire
pour des déploiements multi-utilisateurs (v2.0).
