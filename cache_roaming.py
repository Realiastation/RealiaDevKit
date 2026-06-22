#!/usr/bin/env python3
"""
cache_roaming.py — Gestion du KV Cache via l'API REST de llama.cpp

Utilise les endpoints natifs activés par --slot-save-path :
  - POST /slots/{id}?action=save     -> Sauvegarde le cache KV d'un slot
  - POST /slots/{id}?action=restore   -> Restaure le cache KV d'un slot
  - GET  /slots                      -> État des slots

Le swap de modèle est géré par ModelSwapper (dans devkit_orchestrator.py) :
kill + restart séquentiel, pas de coexistence en VRAM.

Architecture (swap séquentiel, un seul modèle à la fois) :
  ┌─────────────────────────────────────────────┐
  │           cache_roaming.py                   │
  │  ┌──────────┐  ┌──────────┐                 │
  │  │ SlotAPI  │  │ CacheMgr │                 │
  │  │ save/    │  │ suivi    │                 │
  │  │ restore  │  │ stats    │                 │
  │  └──────────┘  └──────────┘                 │
  └─────────────────────────────────────────────┘
                        | HTTP
  ┌─────────────────────────────────────────────┐
  │      llama-server (swap séquentiel)          │
  │  --slot-save-path ./cache_slots              │
  │  UN SEUL modèle chargé à la fois             │
  └─────────────────────────────────────────────┘

Usage:
    from cache_roaming import CacheRoaming

    roaming = CacheRoaming(base_url="http://127.0.0.1:9094")

    # Avant inference : restaurer le slot
    await roaming.restore_slot(slot_id=0, model="Qwen3-Coder-Next-Q4_K_M")

    # Inference...

    # Apres inference : sauvegarder le slot
    await roaming.save_slot(slot_id=0, context_name="session_1")
"""

import json
import logging
import time
import asyncio
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any

import httpx

logger = logging.getLogger("devkit.cache_roaming")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[CACHE_ROAM] %(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)


# =============================================================
#  Modeles de donnees
# =============================================================

@dataclass
class SlotInfo:
    """Etat d'un slot d'inference."""
    id: int
    n_ctx: int
    is_processing: bool
    n_prompt_tokens: int = 0
    n_prompt_tokens_processed: int = 0
    n_prompt_tokens_cache: int = 0
    id_task: Optional[int] = None
    params: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_cache(self) -> bool:
        return self.n_prompt_tokens_cache > 0

    @property
    def progress_pct(self) -> float:
        if self.n_prompt_tokens <= 0:
            return 0.0
        return round(self.n_prompt_tokens_processed / self.n_prompt_tokens * 100, 1)


@dataclass
class RoamingMetrics:
    """Metriques de performance du cache roaming."""
    saves: int = 0
    restores: int = 0
    fails: int = 0
    total_save_time_ms: float = 0.0
    total_restore_time_ms: float = 0.0

    @property
    def avg_save_time_ms(self) -> float:
        return round(self.total_save_time_ms / self.saves, 2) if self.saves > 0 else 0.0

    @property
    def avg_restore_time_ms(self) -> float:
        return round(self.total_restore_time_ms / self.restores, 2) if self.restores > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "saves": self.saves,
            "restores": self.restores,
            "fails": self.fails,
            "avg_save_time_ms": self.avg_save_time_ms,
            "avg_restore_time_ms": self.avg_restore_time_ms,
        }


# =============================================================
#  API Client
# =============================================================

class SlotAPI:
    """Gestion des slots d'inference via l'API REST."""

    MODEL_MAP = {
        "qwen3.6-35b": "Qwen3.6-35B-A3B-UD-Q4_K_M",
        "qwen3-coder-next": "Qwen3-Coder-Next-Q4_K_M",
        "gemma4-12b": "gemma-4-12b-it-Q4_K_M",
    }

    def __init__(self, base_url: str = "http://127.0.0.1:9094"):
        self.base_url = base_url.rstrip("/")
        self._http: Optional[httpx.AsyncClient] = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
        return self._http

    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    def _resolve_model(self, model: str) -> str:
        """Resout un nom court en nom GGUF complet."""
        return self.MODEL_MAP.get(model, model)

    # -- Gestion des Slots -------------------------------------------

    async def list_slots(self) -> List[SlotInfo]:
        """Recupere l'etat de tous les slots via GET /slots."""
        try:
            resp = await self.http.get(f"{self.base_url}/slots")
            resp.raise_for_status()
            data = resp.json()
            slots = []
            for s in data:
                slots.append(SlotInfo(
                    id=s.get("id", 0),
                    n_ctx=s.get("n_ctx", 8192),
                    is_processing=s.get("is_processing", False),
                    n_prompt_tokens=s.get("n_prompt_tokens", 0),
                    n_prompt_tokens_processed=s.get("n_prompt_tokens_processed", 0),
                    n_prompt_tokens_cache=s.get("n_prompt_tokens_cache", 0),
                    id_task=s.get("id_task"),
                    params=s.get("params", {}),
                ))
            return slots
        except Exception as e:
            logger.error(f"SLOTS_LIST_FAIL | {e}")
            return []

    async def save_slot(self, slot_id: int = 0, context_name: str = "default", model: Optional[str] = None) -> bool:
        """Sauvegarde le KV cache d'un slot via POST /slots/{id}?action=save.

        Necessite --slot-save-path au demarrage de llama-server.
        Temps moyen : < 1ms (ecriture fichier mmap en RAM).

        Args:
            slot_id: ID du slot (0-3)
            context_name: nom du fichier de cache (sans chemin, sera stocké dans --slot-save-path)
            model: nom GGUF du modèle (nécessaire en mode router pour router vers le bon child)
        """
        t0 = time.perf_counter()
        try:
            payload = {"filename": f"{context_name}.bin"}
            if model:
                payload["model"] = model
            resp = await self.http.post(
                f"{self.base_url}/slots/{slot_id}?action=save",
                json=payload,
            )
            data = resp.json()
            elapsed = (time.perf_counter() - t0) * 1000

            if resp.status_code == 200:
                n_saved = data.get("n_saved", 0)
                n_written = data.get("n_written", 0)
                save_ms = data.get("timings", {}).get("save_ms", 0)
                logger.info(f"SLOT_SAVE_OK | slot={slot_id} | file={context_name}.bin | "
                           f"tokens_saved={n_saved} | bytes={n_written} | {save_ms}ms")
                return True
            else:
                error_msg = data.get("error", {}).get("message", "unknown")
                logger.warning(f"SLOT_SAVE_FAIL | slot={slot_id} | {error_msg} | {elapsed:.1f}ms")
                return False
        except Exception as e:
            logger.error(f"SLOT_SAVE_ERROR | slot={slot_id} | {e}")
            return False

    async def restore_slot(self, slot_id: int = 0, context_name: str = "default", model: Optional[str] = None) -> bool:
        """Restaure le KV cache d'un slot via POST /slots/{id}?action=restore.
        
        Temps moyen : < 1ms (lecture fichier mmap en RAM).

        Args:
            slot_id: ID du slot (0-3)
            context_name: nom du fichier de cache (sans chemin, relatif à --slot-save-path)
            model: nom GGUF du modèle (nécessaire en mode router)
        """
        t0 = time.perf_counter()
        try:
            payload = {"filename": f"{context_name}.bin"}
            if model:
                payload["model"] = model
            resp = await self.http.post(
                f"{self.base_url}/slots/{slot_id}?action=restore",
                json=payload,
            )
            data = resp.json()
            elapsed = (time.perf_counter() - t0) * 1000

            if resp.status_code == 200:
                n_restored = data.get("n_restored", 0)
                n_read = data.get("n_read", 0)
                restore_ms = data.get("timings", {}).get("restore_ms", 0)
                logger.info(f"SLOT_RESTORE_OK | slot={slot_id} | file={context_name}.bin | "
                           f"tokens_restored={n_restored} | bytes={n_read} | {restore_ms}ms")
                return True
            else:
                error_msg = data.get("error", {}).get("message", "unknown")
                logger.warning(f"SLOT_RESTORE_FAIL | slot={slot_id} | {error_msg} | {elapsed:.1f}ms")
                return False
        except Exception as e:
            logger.error(f"SLOT_RESTORE_ERROR | slot={slot_id} | {e}")
            return False

    # -- Gestion des Modeles (lecture seule, swap géré par ModelSwapper) ---

    async def list_models(self) -> List[Dict[str, Any]]:
        """Liste les modeles disponibles et leur statut via GET /models."""
        try:
            resp = await self.http.get(f"{self.base_url}/models")
            resp.raise_for_status()
            data = resp.json()
            return data.get("models", data.get("data", []))
        except Exception as e:
            logger.error(f"MODELS_LIST_FAIL | {e}")
            return []

    async def get_active_model(self) -> Optional[str]:
        """Retourne le nom du modele actuellement charge, ou None."""
        models = await self.list_models()
        for m in models:
            caps = m.get("capabilities", [])
            if caps:
                return m.get("name") or m.get("id") or m.get("model")
        return None


# =============================================================
#  Cache Manager -- Orchestration haut niveau
# =============================================================

class CacheRoaming:
    """Gestionnaire de cache roaming pour l'orchestrateur.
    
    Usage typique dans _call_utu() :
        roaming = CacheRoaming()
        
        # 1. Swap séquentiel (kill + restart, géré par ModelSwapper)
        
        # 2. Restaurer le slot avant inference
        await roaming.restore_slot(slot_id=0)
        
        # 3. Inference LLM...
        
        # 4. Sauvegarder le slot apres inference
        await roaming.save_slot(slot_id=0)
    """

    def __init__(self, base_url: str = "http://127.0.0.1:9094", max_slots: int = 4):
        self.api = SlotAPI(base_url)
        self.max_slots = max_slots
        self.metrics = RoamingMetrics()
        self._current_model: Optional[str] = None
        self._context_name: str = "default"

    async def close(self):
        await self.api.close()

    @property
    def current_model(self) -> Optional[str]:
        return self._current_model

    @current_model.setter
    def current_model(self, model: str):
        self._current_model = self.api._resolve_model(model)

    # -- Swap de modele géré par ModelSwapper (dans devkit_orchestrator) --
    # Le swap séquentiel (kill + restart) est assuré par la classe ModelSwapper
    # définie dans devkit_orchestrator.py. CacheRoaming gère uniquement le
    # save/restore des slots KV via l'API REST de llama.cpp.

    # -- Save / Restore slots ----------------------------------------

    async def save_slot(self, slot_id: int = 0, context_name: Optional[str] = None, model: Optional[str] = None) -> bool:
        """Sauvegarde le KV cache d'un slot.
        
        Args:
            slot_id: ID du slot (0-3)
            context_name: nom du contexte (devient filename dans le cache)
            model: nom GGUF du modèle (requis en mode router)
        """
        name = context_name or self._context_name
        t0 = time.perf_counter()
        ok = await self.api.save_slot(slot_id, name, model=model or self._current_model)
        elapsed = (time.perf_counter() - t0) * 1000
        if ok:
            self.metrics.saves += 1
            self.metrics.total_save_time_ms += elapsed
        else:
            self.metrics.fails += 1
        return ok

    async def restore_slot(self, slot_id: int = 0, context_name: Optional[str] = None, model: Optional[str] = None) -> bool:
        """Restaure le KV cache d'un slot.
        
        Args:
            slot_id: ID du slot (0-3)
            context_name: nom du contexte (filename dans le cache)
            model: nom GGUF du modèle (requis en mode router)
        """
        name = context_name or self._context_name
        t0 = time.perf_counter()
        ok = await self.api.restore_slot(slot_id, name, model=model or self._current_model)
        elapsed = (time.perf_counter() - t0) * 1000
        if ok:
            self.metrics.restores += 1
            self.metrics.total_restore_time_ms += elapsed
        else:
            self.metrics.fails += 1
        return ok

    async def find_idle_slot(self) -> Optional[int]:
        """Trouve un slot libre."""
        slots = await self.api.list_slots()
        for s in slots:
            if not s.is_processing:
                return s.id
        return None

    async def health_check(self) -> bool:
        """Verifie que le serveur repond."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.api.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    def metrics_report(self) -> Dict[str, Any]:
        """Rapport des metriques de performance."""
        return self.metrics.to_dict()


# =============================================================
#  Utilitaire CLI
# =============================================================

async def cli_status():
    """Affiche l'etat du serveur, des slots et du modele actif."""
    roaming = CacheRoaming()

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   Cache Roaming -- Status Check                           ║")
    print("╠══════════════════════════════════════════════════════════════╣")

    ok = await roaming.health_check()
    print(f"║  Health     : {'OK' if ok else 'DOWN'}")

    if not ok:
        print("╚══════════════════════════════════════════════════════════════╝")
        return

    model = await roaming.api.get_active_model()
    print(f"║  Modele     : {model or '(aucun)'}")

    slots = await roaming.api.list_slots()
    print(f"║  Slots      : {len(slots)} trouves")
    for s in slots:
        cache_status = "cache" if s.has_cache else "vide"
        proc_status = "actif" if s.is_processing else "idle"
        print(f"║    Slot {s.id}  : {proc_status} | {cache_status} | ctx={s.n_ctx}")

    m = roaming.metrics
    print(f"║  Metriques  : saves={m.saves} restores={m.restores}")
    if m.saves > 0:
        print(f"║    Temps    : save avg {m.avg_save_time_ms}ms | restore avg {m.avg_restore_time_ms}ms")

    print("╚══════════════════════════════════════════════════════════════╝")
    await roaming.close()


if __name__ == "__main__":
    asyncio.run(cli_status())
