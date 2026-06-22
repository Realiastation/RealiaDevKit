#!/usr/bin/env python3
"""
Dream Pipeline — Consolidation mémorielle asynchrone (Dreaming V3)
Station Realia — Module de "rêve" qui fusionne les logs bruts en mémoire structurée.

Usage :
    python3 dream_pipeline.py          # Rêve sur les dernières 24h
    python3 dream_pipeline.py --days 3 # Rêve sur les 3 derniers jours
    python3 dream_pipeline.py --dry-run # Aperçu du prompt sans appel API
"""
import json
import os
import glob
import re
import sys
from datetime import datetime, timezone
from typing import Optional

import requests

# Importer le skill d'archivage partagé
from archive_skill import prepare_archive_chunk

# ══════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════════════════════════

API_URL = "http://localhost:9094/v1/chat/completions"
MODEL_NAME = "qwen3.6-35b"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(BASE_DIR, "state_memoire.json")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# ══════════════════════════════════════════════════════════════════════════
# GESTION DU FICHIER MÉMOIRE
# ══════════════════════════════════════════════════════════════════════════

MEMOIRE_PAR_DEFAUT = {
    "last_synced": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "identity": {
        "stack_techno": "Python, Linux, Docker, llama.cpp, RTX 4080, 128GB RAM",
        "projets_actifs": {
            "DevKit": "Interface locale multi-agent, swap dynamique de modèles GGUF.",
            "StationRealia": "Projet global multimodal."
        }
    },
    "preferences_systeme": [
        "Toujours générer du code propre, modulaire et commenté en français.",
        "Prioriser les solutions locales sans API tierces."
    ],
    "evenements_temporels": []
}


def load_memory() -> dict:
    """
    Charge state_memoire.json.
    Si le fichier n'existe pas, crée la mémoire par défaut et la sauvegarde.
    """
    if not os.path.exists(MEMORY_FILE):
        print(f"[Dream] 🆕 Aucune mémoire trouvée -> création du fichier par défaut")
        save_memory(MEMOIRE_PAR_DEFAUT)
        return dict(MEMOIRE_PAR_DEFAUT)

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"[Dream] 📖 Mémoire chargée depuis {MEMORY_FILE}")
        return data
    except (json.JSONDecodeError, IOError) as e:
        print(f"[Dream] ⚠️ Erreur de lecture mémoire: {e} -> réinitialisation")
        save_memory(MEMOIRE_PAR_DEFAUT)
        return dict(MEMOIRE_PAR_DEFAUT)


def save_memory(data: dict) -> None:
    """Écrase state_memoire.json avec le nouveau JSON (indenté 2 espaces)."""
    try:
        data["last_synced"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[Dream] 💾 Mémoire sauvegardée dans {MEMORY_FILE}")
    except IOError as e:
        print(f"[Dream] ❌ Erreur sauvegarde mémoire: {e}")


# ══════════════════════════════════════════════════════════════════════════
# RÉCUPÉRATION DES LOGS
# ══════════════════════════════════════════════════════════════════════════

def get_recent_logs(days: int = 1) -> str:
    """
    Lit les fichiers logs/YYYY-MM-DD.jsonl des N derniers jours.

    Retourne une chaîne formatée :
        [HH:MM] agent/role: contenu
    """
    if not os.path.isdir(LOGS_DIR):
        print(f"[Dream] 📂 Dossier logs/ introuvable -> aucun log à traiter")
        return ""

    lignes = []
    now = datetime.now()

    for i in range(days):
        date_str = (now.replace(hour=0, minute=0, second=0, microsecond=0) -
                     __import__('datetime').timedelta(days=i)).strftime("%Y-%m-%d")
        log_path = os.path.join(LOGS_DIR, f"{date_str}.jsonl")

        if not os.path.exists(log_path):
            continue

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        ts = record.get("timestamp", "")
                        # Extraire HH:MM du timestamp ISO
                        time_part = ts[11:16] if len(ts) >= 16 else ts
                        agent = record.get("agent", "?")
                        role = record.get("role", "?")
                        content = record.get("content", "")
                        # Tronquer les contenus trop longs
                        if len(content) > 500:
                            content = content[:500] + "..."
                        lignes.append(f"[{time_part}] {agent}/{role}: {content}")
                    except json.JSONDecodeError:
                        continue
        except IOError as e:
            print(f"[Dream] ⚠️ Erreur lecture {log_path}: {e}")
            continue

    if not lignes:
        print(f"[Dream] 📭 Aucun log trouvé sur les {days} dernier(s) jour(s)")
        return ""

    result = "\n".join(lignes)
    print(f"[Dream] 📜 {len(lignes)} lignes de logs consolidées sur {days} jour(s)")
    return result


# ══════════════════════════════════════════════════════════════════════════
# PROMPT DU RÊVEUR
# ══════════════════════════════════════════════════════════════════════════

TEMPLATE_REVE = (
    "Tu es l'Archiviste Système du projet Realia.\n"
    "Ta mission : fusionner les flux de logs condensés ci-dessous avec l'état actuel "
    "de state_memoire.json pour produire un JSON de mémoire mis à jour, propre et fidèle.\n\n"
    "Voici l'état actuel de la mémoire :\n"
    "{state_memoire_actuel}\n\n"
    "Voici les logs du jour (format condensé par archive_skill) :\n"
    "{logs_du_jour}\n\n"
    "Consignes strictes de mise à jour :\n"
    "1. PRIORITÉ AUX FLUSH DE SLIDING WINDOW : Les entrées JSONL avec "
    "\"type\": \"sliding_window_flush\" contiennent le contexte immédiat des échanges "
    "utilisateur-modèle de la session. Elles sont PLUS RÉCENTES et PLUS PERTINENTES que "
    "les logs d'interaction standards. Analyse-les en priorité pour détecter des "
    "changements d'état, des préférences exprimées, ou des décisions techniques.\n"
    "2. ANALYSE DU TEMPS : Repère les dates dans les logs. Si un projet marqué \"en cours\" "
    "dans la mémoire semble terminé dans les logs, passe-le en \"terminé\".\n"
    "3. CONTRADICTIONS : Si l'utilisateur change d'avis (ex: abandonne une techno), "
    "corrige la structure immédiatement, ne conserve pas l'ancienne version.\n"
    "4. CONCISION ABSOLUE : Ne garde que les contraintes techniques objectives, "
    "les préférences exprimées explicitement, et l'état d'avancement des projets. "
    "Supprime tout bavardage, remerciement, salutation, ou commentaire sans valeur.\n"
    "5. FIDÉLITÉ STRICTE : Ne déduis RIEN qui ne soit pas explicitement dans les logs. "
    "Si un projet n'est pas mentionné, laisse son statut inchangé.\n\n"
    "Renvoie UNIQUEMENT le JSON mis à jour, valide, sans fioritures, ni balises "
    "markdown additionnelles, ni commentaires.\n"
    "\n"
    "RÈGLE ABSOLUE : Ta réponse DOIT être uniquement le JSON brut. "
    "N'encapsule PAS le JSON dans des balises markdown (```json ... ```). "
    "Ne mets AUCUN texte avant ou après le JSON."
)


def build_prompt(memory: dict, logs_text: str) -> str:
    """Construit le prompt complet à envoyer à l'API."""
    memory_json = json.dumps(memory, indent=2, ensure_ascii=False)
    logs_text = logs_text if logs_text else "(aucun nouveau log aujourd'hui)"
    return TEMPLATE_REVE.format(
        state_memoire_actuel=memory_json,
        logs_du_jour=logs_text
    )


# ══════════════════════════════════════════════════════════════════════════
# APPEL API & PARSING
# ══════════════════════════════════════════════════════════════════════════

def call_dream_api(memory, logs_text: str) -> Optional[str]:
    """
    Envoie le prompt à l'API llama.cpp et retourne la réponse brute.

    Avant l'appel API, les logs bruts sont nettoyés par le skill
    d'archivage (archive_skill.py) qui filtre le boilerplate système,
    tronque les contenus à 500 caractères et limite la taille totale.

    Args:
        memory: dict de la mémoire actuelle (ou str JSON)
        logs_text: logs formatés des dernières 24h (bruts, avant filtrage)

    Returns:
        str: réponse brute du modèle, ou None si échec
    """
    # Si memory est un dict, le convertir en JSON string
    if isinstance(memory, dict):
        memory_str = json.dumps(memory, indent=2, ensure_ascii=False)
    else:
        memory_str = str(memory)

    # Utiliser le skill d'archivage pour nettoyer les logs
    # (logs_text est déjà le résultat de get_recent_logs, on le repasse
    # par archive_skill pour un filtrage plus agressif)
    condensed_logs = logs_text
    # On tente de charger le fichier JSONL du jour pour appliquer le skill
    today_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(LOGS_DIR, f"{today_str}.jsonl")
    if os.path.exists(log_file):
        archived = prepare_archive_chunk(log_file, max_chars=8000)
        if archived and not archived.startswith("[Archive]"):
            condensed_logs = archived
            print(f"[Dream] 🗂️ Logs condensés via archive_skill ({len(archived)} car.)")

    prompt = build_prompt(memory_str, condensed_logs)

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.1,  # Température basse = zéro hallucination, Archiviste fidèle
        "max_tokens": 4096,
        "top_p": 0.95,
        "top_k": 40,
        "stream": False,
        "n_predict": 4096,
        "stop": []
    }

    headers = {
        "Content-Type": "application/json"
    }

    print(f"[Dream] 🌙 Appel API Qwen3.6 (rêve en cours...)")
    try:
        resp = requests.post(API_URL, json=payload, headers=headers, timeout=180.0)
        if resp.status_code != 200:
            print(f"[Dream] ❌ API error: {resp.status_code} - {resp.text[:200]}")
            return None

        data = resp.json()
        response_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"[Dream] ✅ Réponse reçue ({len(response_text)} caractères)")
        return response_text

    except requests.exceptions.Timeout:
        print(f"[Dream] ⏱️ Timeout API (180s dépassé)")
        return None
    except requests.exceptions.ConnectionError:
        print(f"[Dream] 🔴 Connexion refusée: llama-server est-il actif sur :9094 ?")
        return None
    except Exception as e:
        print(f"[Dream] ❌ Erreur inattendue: {e}")
        return None


def parse_json_response(response_text: str) -> Optional[dict]:
    """
    Extrait le JSON valide de la réponse du LLM.

    Les LLM ajoutent souvent des balises ```json ... ```.
    Utilise une regex pour extraire uniquement le bloc JSON.
    Retente 1 fois si échec (log l'erreur).

    Args:
        response_text: réponse brute du modèle

    Returns:
        dict: JSON parsé, ou None si échec
    """
    if not response_text:
        print(f"[Dream] ⚠️ Réponse vide — impossible de parser")
        return None

    # ── ÉTAPE 0 : Nettoyage systématique des balises markdown ──
    # Qwen3.6 encapsule fréquemment ses réponses JSON dans ```json ... ```
    # ou ``` ... ```, malgré la consigne contraire dans le prompt.
    # On retire TOUTES les balises de bloc markdown avant de tenter le parse.
    cleaned = response_text.strip()
    # Retirer les blocs ```json ... ``` et ``` ... ```
    cleaned = re.sub(
        r'```(?:json)?\s*\n?([\s\S]*?)\n?\s*```',
        r'\1',
        cleaned,
        flags=re.DOTALL
    )
    # Retirer les backticks simples en début/fin de ligne
    cleaned = re.sub(r'^`+|`+$', '', cleaned)
    # Retirer les espaces et lignes vides superflus en début/fin
    cleaned = cleaned.strip()

    # ── ÉTAPE 0b : Tentative directe sur le texte nettoyé ──
    # Si le nettoyage a retiré les balises, le JSON brut est directement lisible
    if cleaned != response_text:
        try:
            data = json.loads(cleaned)
            print(f"[Dream] ✅ JSON parsé (après nettoyage markdown étape 0)")
            return data
        except json.JSONDecodeError:
            pass  # Le nettoyage n'a pas suffi, on continue avec le texte original

    # Étape 1 : essayer d'extraire un bloc ```json ... ``` (le cas le plus fréquent)
    match = re.search(r'```(?:json)?\s*\n?(\{.*?\})\n?\s*```', response_text, re.DOTALL)
    if match:
        json_str = match.group(1)
        try:
            data = json.loads(json_str)
            print(f"[Dream] ✅ JSON parsé (extrait bloc ```json)")
            return data
        except json.JSONDecodeError:
            pass  # Continuer vers les autres méthodes

    # Étape 2 : chercher le premier { et dernier } dans tout le texte
    match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if match:
        json_str = match.group(0)
        try:
            data = json.loads(json_str)
            print(f"[Dream] ✅ JSON parsé (extraction regex générale)")
            return data
        except json.JSONDecodeError as e:
            print(f"[Dream] ⚠️ JSON invalide (tentative 1): {e}")
            # Essai correctif : remplacer les quotes simples par doubles
            try:
                fixed = json_str.replace("'", '"')
                data = json.loads(fixed)
                print(f"[Dream] ✅ JSON parsé après correction quotes")
                return data
            except json.JSONDecodeError:
                pass

    # Étape 3 : tentative directe sur toute la réponse
    try:
        data = json.loads(response_text.strip())
        print(f"[Dream] ✅ JSON parsé (direct)")
        return data
    except json.JSONDecodeError:
        pass

    print(f"[Dream] ❌ Échec parsing JSON après toutes les tentatives")
    print(f"[Dream]    Début réponse: {response_text[:200]}")
    return None


# ══════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ══════════════════════════════════════════════════════════════════════════

def main(days: int = 1):
    """
    Cycle de rêve complet :
    1. Charger la mémoire actuelle
    2. Récupérer les logs récents
    3. Appeler l'API de consolidation
    4. Parser la réponse
    5. Sauvegarder la nouvelle mémoire
    """
    print(f"\n{'='*60}")
    print(f"🌙 DREAM PIPELINE — Consolidation mémorielle")
    print(f"{'='*60}")
    print(f"   Mémoire : {MEMORY_FILE}")
    print(f"   Logs     : {LOGS_DIR}/ (derniers {days} jour(s))")
    print(f"   Modèle   : {MODEL_NAME} sur {API_URL}")
    print()

    # 1. Charger la mémoire
    memory = load_memory()

    # 2. Récupérer les logs
    logs_text = get_recent_logs(days=days)

    # 3. Appeler l'API
    response = call_dream_api(memory, logs_text)
    if response is None:
        print(f"\n[Dream] ⛔ Rêve avorté — mémoire actuelle conservée")
        return 1

    # 4. Parser la réponse
    new_memory = parse_json_response(response)
    if new_memory is None:
        print(f"\n[Dream] ⛔ Rêve incomplet — mémoire actuelle conservée")
        return 1

    # 5. Sauvegarder
    save_memory(new_memory)

    print(f"\n{'='*60}")
    print(f"✅ RÊVE TERMINÉ — Mémoire consolidée avec succès")
    print(f"{'='*60}")
    print(f"   Projets : {list(new_memory.get('identity', {}).get('projets_actifs', {}).keys())}")
    prefs = new_memory.get("preferences_systeme", [])
    print(f"   Préférences : {len(prefs)} règle(s)")
    events = new_memory.get("evenements_temporels", [])
    print(f"   Événements  : {len(events)} entrée(s)")
    print()
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Dream Pipeline — Consolidation mémorielle Realia"
    )
    parser.add_argument(
        "--days", type=int, default=1,
        help="Nombre de jours de logs à consolider (défaut: 1)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche le prompt sans appeler l'API (debug)"
    )
    args = parser.parse_args()

    if args.dry_run:
        print(f"\n{'='*60}")
        print(f"🔍 DRY RUN — Aperçu du prompt sans appel API")
        print(f"{'='*60}")
        memory = load_memory()
        logs = get_recent_logs(days=args.days)
        prompt = build_prompt(memory, logs)
        print(f"\n--- PROMPT ({len(prompt)} caractères) ---")
        print(prompt[:3000])
        if len(prompt) > 3000:
            print(f"\n... [tronqué, {len(prompt) - 3000} caractères supplémentaires]")
        print("\n--- FIN PROMPT ---")
        sys.exit(0)

    sys.exit(main(days=args.days))
