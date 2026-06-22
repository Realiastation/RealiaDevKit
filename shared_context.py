"""shared_context.py — Contexte partage JSON-Flash pour hot-swap router.

Formatte l'etat (RAG + Historique + Session) en payload ultra-condense
pour initialiser le contexte d'un modele charge via POST /models/load.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Base racine du projet (dynamique) ────────────────
BASE_DIR = Path(__file__).resolve().parent
# =====================================================

logger = logging.getLogger("devkit.shared_context")


class SharedContext:
    """Gere le contexte partage entre les modeles Gemma4 et Qwen3."""

    def __init__(self, rag_dir: Optional[str] = None):
        self.history: List[Dict[str, str]] = []
        self.rag_index: List[Dict[str, Any]] = []
        self.session_vars: Dict[str, Any] = {}
        self._rag_path = Path(rag_dir or str(BASE_DIR / "rag"))
        self._load_rag_index()

    def _load_rag_index(self):
        """Charge le fichier RAG index.jsonl."""
        index_path = self._rag_path / "index.jsonl"
        if index_path.exists():
            try:
                with open(index_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            self.rag_index.append(json.loads(line))
                logger.info(f"RAG_INDEX_LOADED | entries={len(self.rag_index)}")
            except Exception as e:
                logger.warning(f"RAG_INDEX_ERROR | {e}")

    def add_message(self, role: str, content: str):
        """Ajoute un message a l'historique de session."""
        self.history.append({"role": role, "content": content})
        if len(self.history) > 20:
            self.history = self.history[-20:]

    def set_session_var(self, key: str, value: Any):
        """Stocke une variable de session."""
        self.session_vars[key] = value

    def to_json_flash(self, task_context: str = "") -> str:
        """Produit un payload JSON ultra-condense pour initialiser le contexte."""
        rag_top = self.rag_index[-3:] if self.rag_index else []
        last_turn = self.history[-2:] if self.history else []
        payload = {
            "rag": [{"type": c.get("type", "text"), "content": c.get("content", "")[:500]}
                    for c in rag_top],
            "history": [{"role": m["role"], "content": m["content"][:500]} for m in last_turn],
            "session": self.session_vars,
            "task": task_context[:1000] if task_context else "",
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def format_system_prompt(self, task_context: str = "") -> str:
        """Formatte le contexte comme un system prompt enrichi."""
        flash = json.loads(self.to_json_flash(task_context))
        parts = []
        if flash["rag"]:
            rag_text = "\n".join(
                f"[RAG {c['type']}]: {c['content']}" for c in flash["rag"]
            )
            parts.append(f"## Contexte RAG\n{rag_text}")
        if flash["history"]:
            hist_text = "\n".join(
                f"{m['role']}: {m['content']}" for m in flash["history"]
            )
            parts.append(f"## Historique\n{hist_text}")
        if flash["session"]:
            sess_text = "\n".join(f"{k}: {v}" for k, v in flash["session"].items())
            parts.append(f"## Session\n{sess_text}")
        if flash["task"]:
            parts.append(f"## Tache\n{flash['task']}")
        return "\n\n".join(parts)


# Singleton global
_context_instance: Optional[SharedContext] = None


def get_shared_context() -> SharedContext:
    """Retourne l'instance singleton du contexte partage."""
    global _context_instance
    if _context_instance is None:
        _context_instance = SharedContext()
    return _context_instance


def reset_shared_context():
    """Reinitialise le contexte (pour tests ou nouvelle session)."""
    global _context_instance
    _context_instance = SharedContext()
