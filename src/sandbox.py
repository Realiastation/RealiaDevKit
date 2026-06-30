"""
Sandbox module — Isolation et sécurité pour écriture fichiers.
Genesis Protocol : principle_4_sandbox_isolation
"""
import shutil
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# === CONSTANTES ===
BASE_DIR = Path(os.environ.get("REALIA_BASE_DIR", Path(__file__).parent))
SANDBOX = BASE_DIR


# === FONCTIONS PUBLIQUES ===
def check_sandbox(path: str) -> Path:
    """Vérifie que le chemin est dans le sandbox.

    Args:
        path: Chemin à vérifier

    Returns:
        Path résolue si valide

    Raises:
        PermissionError: Si le chemin est hors sandbox
    """
    p = Path(path).resolve()
    if not p.is_relative_to(SANDBOX):
        raise PermissionError(
            f"Chemin hors sandbox: {path} (sandbox={SANDBOX})"
        )
    return p


def is_safe_path(path: str) -> bool:
    """Vérifie si un chemin est dans le sandbox (sans lever d'exception).

    Args:
        path: Chemin à vérifier

    Returns:
        True si le chemin est dans le sandbox, False sinon
    """
    try:
        p = Path(path).resolve()
        return p.is_relative_to(SANDBOX)
    except Exception:
        return False


def create_backup(path: Path) -> Optional[Path]:
    """Crée un backup .bak.realia du fichier.

    Args:
        path: Chemin du fichier à backuper

    Returns:
        Chemin du backup créé, ou None si échec
    """
    try:
        backup_path = Path(str(path) + ".bak.realia")
        if path.exists():
            shutil.copy2(str(path), str(backup_path))
            logger.info(f"BACKUP_CREATED | path={backup_path}")
        return backup_path
    except Exception as e:
        logger.warning(f"BACKUP_FAILED | path={path} | error={e}")
        return None


def sandbox_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Écrit dans le sandbox avec backup automatique.

    Args:
        path: Chemin du fichier à écrire
        content: Contenu à écrire
        encoding: Encodage (défaut: utf-8)

    Raises:
        PermissionError: Si le chemin est hors sandbox
    """
    safe_path = check_sandbox(str(path))
    create_backup(safe_path)
    safe_path.write_text(content, encoding=encoding)
    logger.info(f"FILE_WRITTEN | path={safe_path} | size={len(content)}")


if __name__ == "__main__":
    # Test rapide
    print(f"SANDBOX = {SANDBOX}")
    print(f"BASE_DIR = {BASE_DIR}")
    print(f"is_safe_path('.') = {is_safe_path('.')}")
    print(f"is_safe_path('/etc/passwd') = {is_safe_path('/etc/passwd')}")
