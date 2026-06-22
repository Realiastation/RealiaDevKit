"""
build_hierarchical_prompt.py
Hiérarchie stricte N1→N4 pour max Cache Hits llama.cpp.
N1: Système RealiaDev (immuable)
N2: RAG Long-Terme (immuable entre appels swarm)
N3: RAG Court-Terme / Flash JSON (variable par étape)
N4: Input Utilisateur (variable)
Ordre rigoureux. Tagging des ruptures pour debug.
"""

import hashlib
from typing import Optional

# ── Séparateurs ──────────────────────────────────────────────────────────
SEP = "\n\n---\n\n"
TAG_BREAK = "[BREAK]"

# ── N1: Système RealiaDev ───────────────────────────────────────────────
N1_SYSTEM = f"""Tu es RealiaDev, un agent orchestrateur multimodal.
Tu utilises Gemma4-E4B comme modèle principal, DeepSeek-R1 pour le raisonnement,
et Qwen-Coder pour la génération de code.
Réponds en français. Sois méthodique et clair.
Accessibilité C6-C7 : privilégie la lisibilité.
{TAG_BREAK}"""

# ── N2 par défaut (surchargé par RAG) ──────────────────────────────────
N2_RAG_DEFAULT = "[RAG Long-Terme : Aucun contexte longue durée chargé.]"


def build_hierarchical_prompt(
    n1: Optional[str] = None,
    n2: Optional[str] = None,
    n3: Optional[str] = None,
    n4: Optional[str] = None,
) -> str:
    """Concatène les 4 niveaux dans l'ordre strict N1→N2→N3→N4.
    Chaque niveau est séparé par SEP et taggé avec son niveau.
    Retourne le prompt complet prêt pour llama.cpp.
    """
    parts = []
    parts.append(f"[N1: Système]\n{(n1 or N1_SYSTEM).strip()}")
    parts.append(f"[N2: RAG Long-Terme]\n{(n2 or N2_RAG_DEFAULT).strip()}")
    if n3 and n3.strip():
        parts.append(f"[N3: RAG Court-Terme]\n{n3.strip()}")
    if n4 and n4.strip():
        parts.append(f"[N4: Input Utilisateur]\n{n4.strip()}")
    return SEP.join(parts)


def hash_prefix(n1: str, n2: str) -> str:
    """Hash du préfixe N1+N2 pour identifier le cache partagé."""
    raw = (n1 or N1_SYSTEM) + (n2 or N2_RAG_DEFAULT)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def build_prompt_with_rag(
    user_input: str,
    rag_long: Optional[str] = None,
    rag_short: Optional[str] = None,
) -> tuple[str, str]:
    """Wrapper pratique : retourne (prompt_complet, prefix_hash)."""
    n1 = N1_SYSTEM
    n2 = rag_long or N2_RAG_DEFAULT
    n3 = rag_short
    n4 = user_input
    prompt = build_hierarchical_prompt(n1=n1, n2=n2, n3=n3, n4=n4)
    ph = hash_prefix(n1, n2)
    return prompt, ph
