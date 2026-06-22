#!/usr/bin/env python3
"""contract_manager.py — Gestion thread-safe du fichier Contrat-Travail partagé.

Machine à états distribuée entre les modèles (Q3.6, Q3N, G4E12B).
Utilise fcntl.flock pour le verrouillage POSIX et os.replace pour l'écriture
atomique, garantissant l'intégrité du contrat même en cas de crash.

Schéma :
    ContratTravail : conteneur racine
        ├── projet_id        (str)
        ├── status           (str: INIT|PLANNING|CODING|REVIEW|DONE|FAILED)
        ├── workflow         (WorkflowRoute)
        │   ├── current_actor
        │   ├── next_actor_requested
        │   ├── reason
        │   ├── task_description
        │   └── consensus_mode
        ├── consensus_requis (List[str])
        ├── validations_actuelles (Dict[str,bool])
        ├── contexte_partage (Dict[str,str])
        └── history          (List[str])
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─── Schémas Pydantic ───────────────────────────────────────────────────────

class WorkflowRoute(BaseModel):
    """État actuel et prochain du routage entre modèles."""

    current_actor: str = "Q3.6"
    next_actor_requested: Optional[str] = None
    reason: str = ""
    task_description: str = ""
    consensus_mode: bool = False


class ContratTravail(BaseModel):
    """Contrat de travail partagé entre modèles (State Machine distribuée)."""

    projet_id: str
    status: str = "INIT"  # INIT | PLANNING | CODING | REVIEW | DONE | FAILED
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Consensus multi-modèles
    consensus_requis: List[str] = ["Q3.6", "Q3N", "G4E12B"]
    validations_actuelles: Dict[str, bool] = {}

    # Routage dynamique
    workflow: WorkflowRoute = WorkflowRoute()

    # Contexte partagé entre modèles (info clés transmises)
    contexte_partage: Dict[str, str] = {}

    # Historique des actions (pour le Swarm Monitor UI)
    history: List[str] = []


# ─── ContractManager ─────────────────────────────────────────────────────────

class ContractManager:
    """Gestionnaire thread-safe du fichier Contrat-Travail.

    Utilise :
        - fcntl.flock pour le verrouillage POSIX (partagé en lecture,
          exclusif en écriture).
        - os.replace pour l'écriture atomique via fichier .tmp.

    Usage:
        cm = ContractManager("projet-001")
        contrat = cm.read()
        cm.update_and_save({"workflow": {"next_actor_requested": "Q3N"}})
        cm.add_history_entry("Q3.6", "Planification terminée, délégation à Q3N")
    """

    def __init__(
        self,
        projet_id: str,
        filepath: Optional[Path] = None,
    ) -> None:
        """Initialise ou charge le contrat.

        Args:
            projet_id: Identifiant unique du projet.
            filepath: Chemin vers le fichier contrat (défaut : ./contrat_travail.json).
        """
        self.projet_id: str = projet_id
        self._filepath: Path = (
            filepath
            if filepath is not None
            else Path(__file__).parent / "contrat_travail.json"
        )

        # Crée le contrat par défaut si le fichier n'existe pas
        if not self._filepath.exists():
            self._create_default()

    # ─── Propriétés ───────────────────────────────────────────────────────

    @property
    def filepath(self) -> Path:
        return self._filepath

    # ─── Initialisation ───────────────────────────────────────────────────

    def _create_default(self) -> None:
        """Crée un fichier contrat par défaut sur le disque."""
        contrat = ContratTravail(
            projet_id=self.projet_id,
            status="INIT",
            history=[f"[{_now_iso()}] Contrat créé pour le projet '{self.projet_id}'"],
        )
        # Écriture atomique directe
        self._write_atomic(contrat.model_dump(mode="json"))

    # ─── Lecture sécurisée (verrou partagé) ───────────────────────────────

    def read(self) -> ContratTravail:
        """Lit le contrat depuis le disque avec un verrou partagé.

        Returns:
            ContratTravail désérialisé.

        Raises:
            FileNotFoundError: Si le fichier n'existe pas.
            json.JSONDecodeError: Si le fichier est corrompu.
        """
        if not self._filepath.exists():
            raise FileNotFoundError(
                f"Fichier contrat introuvable : {self._filepath}"
            )

        with open(self._filepath, "r", encoding="utf-8") as f:
            # Verrou partagé (LOCK_SH) : plusieurs lecteurs possibles
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                data: Dict[str, Any] = json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

        return ContratTravail(**data)

    # ─── Atomique ─────────────────────────────────────────────────────────

    def _write_atomic(self, data: Dict[str, Any]) -> None:
        """Écrit les données atomiquement via .tmp + os.replace.

        Args:
            data: Dictionnaire à sérialiser en JSON.
        """
        tmp_path: Path = self._filepath.with_suffix(".json.tmp")
        tmp_path_str: str = str(tmp_path)
        target_path_str: str = str(self._filepath)

        with open(tmp_path_str, "w", encoding="utf-8") as f:
            # Verrou exclusif (LOCK_EX) : un seul processus écrit
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Force l'écriture disque
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

        # Remplacement atomique (POSIX guarantee)
        os.replace(tmp_path_str, target_path_str)

    # ─── Écriture sécurisée (verrou exclusif) ─────────────────────────────

    def write(self, contrat: ContratTravail) -> None:
        """Écrit le contrat sur le disque de manière atomique.

        Met automatiquement à jour le champ ``updated_at``.

        Args:
            contrat: Instance ContratTravail à persister.
        """
        contrat.updated_at = _now_iso()
        self._write_atomic(contrat.model_dump(mode="json"))

    # ─── Mise à jour partielle ────────────────────────────────────────────

    def update_and_save(self, update_dict: Dict[str, Any]) -> ContratTravail:
        """Lit, fusionne les mises à jour et sauvegarde atomiquement.

        Les clés de ``update_dict`` sont fusionnées récursivement dans le
        contrat existant. Exemple :
            {"workflow": {"next_actor_requested": "Q3N"},
             "status": "CODING"}

        Args:
            update_dict: Dictionnaire partiel à fusionner.

        Returns:
            ContratTravail mis à jour.

        Raises:
            FileNotFoundError: Si le fichier n'existe pas.
            json.JSONDecodeError: Si le fichier est corrompu.
        """
        contrat: ContratTravail = self.read()

        # Fusion récursive des champs
        updated: Dict[str, Any] = contrat.model_dump(mode="json")
        self._deep_merge(updated, update_dict)

        contrat = ContratTravail(**updated)

        # Ajout automatique dans l'historique
        actor = contrat.workflow.current_actor
        reason = update_dict.get("workflow", {}).get("reason", "")
        action_summary = (
            f"[{_now_iso()}] {actor} → "
            f"status={contrat.status} | "
            f"next={contrat.workflow.next_actor_requested} | "
            f"{reason}"
        )
        contrat.history.append(action_summary)

        self.write(contrat)
        return contrat

    # ─── Utilitaire historique ────────────────────────────────────────────

    def add_history_entry(self, actor: str, action: str) -> None:
        """Ajoute une entrée dans l'historique et sauvegarde.

        Args:
            actor: Nom de l'acteur (ex: "Q3.6", "Q3N", "G4E12B").
            action: Description de l'action.
        """
        contrat: ContratTravail = self.read()
        contrat.history.append(f"[{_now_iso()}] {actor} : {action}")
        self.write(contrat)

    # ─── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
        """Fusion récursive du dictionnaire ``override`` dans ``base``.

        Les feuilles (str, list, etc.) sont remplacées.
        Les dicts sont fusionnés récursivement.

        Args:
            base: Dictionnaire cible (modifié sur place).
            override: Dictionnaire source.
        """
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ContractManager._deep_merge(base[key], value)
            else:
                base[key] = value

    def __repr__(self) -> str:
        return (
            f"<ContractManager projet_id='{self.projet_id}' "
            f"path='{self._filepath}'>"
        )


# ─── Helper ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    """Retourne le timestamp ISO 8601 courant (UTC)."""
    return datetime.now(timezone.utc).isoformat()


# ─── Shortcut ───────────────────────────────────────────────────────────────

def load_or_create(projet_id: str, filepath: Optional[Path] = None) -> ContractManager:
    """Charge un ContractManager existant ou en crée un.

    Args:
        projet_id: Identifiant du projet.
        filepath: Chemin du fichier contrat (optionnel).

    Returns:
        Instance ContractManager prête à l'emploi.
    """
    return ContractManager(projet_id=projet_id, filepath=filepath)


# ─── CLI de test rapide ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage : python3 contract_manager.py <projet_id>")
        sys.exit(1)

    projet_id: str = sys.argv[1]
    cm = ContractManager(projet_id)
    print(f"📄 Contrat chargé/créé : {cm.filepath}")
    contrat = cm.read()
    print(f"\n{contrat.model_dump_json(indent=2)}")

    # Test de mise à jour
    print("\n--- Mise à jour test ---")
    cm.update_and_save({
        "status": "PLANNING",
        "workflow": {
            "current_actor": "Q3.6",
            "next_actor_requested": "Q3N",
            "reason": "Test initial du dossier-contrat",
            "task_description": "Valider le mécanisme de swap",
        },
    })
    contrat2 = cm.read()
    print(f"Status : {contrat2.status}")
    print(f"Next   : {contrat2.workflow.next_actor_requested}")
    print(f"History: {contrat2.history[-1]}")
    print("\n✅ contract_manager.py fonctionnel.")
