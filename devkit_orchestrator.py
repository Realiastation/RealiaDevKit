# 🏛️ ARCHITECTURE FONDAMENTALE : Station Realia = Station Agentique Multimodale
# Cerveau unique : UTU-Agent (Youtu). Sans UTU → pas d'agent → pas de Station.
# 3 modèles en swap séquentiel sur :9094. Aucun fallback externe autorisé.
# Accessibilité C6-C7 : principe de conception, pas un plugin.
import sys, os, json, difflib, subprocess
from pathlib import Path

# ── Base racine du projet (dynamique, anonymise le FS) ──────────────
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = os.environ.get("REALIA_LOG_DIR", str(BASE_DIR / "logs"))
# ====================================================================

from pydantic import BaseModel
import logging, shutil, time, httpx, asyncio, io, base64
from datetime import datetime
from uuid import uuid4
from typing import Optional, Dict, Any

# === Skills & Expérience — Bibliothèque de Boîtes à Conseils Senior ===
try:
    from skills.skill_registry import load_experience_rules, enforce_rules, scan_prompt_for_rules
except ImportError:
    # Module skills non disponible (reserve a la Station)
    load_experience_rules = lambda x: x
    enforce_rules = lambda x, y: x
    scan_prompt_for_rules = lambda x: []

# === Contrat-Travail — State Machine distribuée entre modèles ===
from contract_manager import ContractManager, ContratTravail, WorkflowRoute

# === Cache Roaming — Hot-swap API + Slot KV Cache ===
from cache_roaming import CacheRoaming

# === UTU-Agent Import — Chemin DOCK uniquement ===
UTU_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "youtu-agent")
if os.path.exists(os.path.join(UTU_PATH, "utu", "__init__.py")):
    sys.path.insert(0, UTU_PATH)
    try:
        from utu.agents import SimpleAgent
        UTU_AVAILABLE = True
    except ImportError:
        UTU_AVAILABLE = False
else:
    UTU_AVAILABLE = False
# ================================================

# === Station ToolRegistry Import ===
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from station_privee.tools.registry import ToolRegistry
    TOOL_REGISTRY_AVAILABLE = True
    logger = logging.getLogger("devkit-utu")
    logger.info(f"ToolRegistry chargé ({len(ToolRegistry.list_available())} outils)")
except ImportError as e:
    TOOL_REGISTRY_AVAILABLE = False
    logger = logging.getLogger("devkit-utu")
    logger.warning(f"ToolRegistry non disponible: {e}")

# === Import de l'outil bash (auto-enregistrement dans ToolRegistry) ===
try:
    from station_privee.tools.bash_tool import BashTool  # noqa: F811
    logger.info(f"Outil bash chargé avec succès ({BashTool.description[:50]}...)")
except ImportError as e:
    logger.warning(f"Outil bash non disponible: {e}")
# ================================================

from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── WebSocket API Contract v1.0.0 ────────────────────────────────────
from realia_devkit.ws_server import router as ws_router
from realia_devkit.feature_flags import get_feature_flags, flags
from realia_devkit.ws_broadcaster import broadcaster

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[DevKit-UTU] %(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("devkit-utu")

# ── Logger fichier structuré ──────────────────────────────────────────────
logger = logging.getLogger("devkit.utu")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.FileHandler(str(BASE_DIR / "devkit.log"))
    formatter = logging.Formatter('[%(asctime)s] [%(name)s] %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# ── Observabilité ────────────────────────────────────────────────────────
START_TIME = time.time()
app_start_time = time.time()

def _socket_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False

async def _ensure_llama_server_running():
    """Vérifie que llama-server tourne. Si non, lance start_server.sh.
    À appeler une seule fois au boot (dans startup event).
    """
    if _socket_reachable("127.0.0.1", 9094, timeout=1.0):
        logger.info("LLAMA_SERVER | déjà en cours d'exécution")
        return True
    try:
        import subprocess
        script = str(BASE_DIR / "start_server.sh")
        logger.info(f"LLAMA_SERVER | lancement de {script}...")
        result = subprocess.run([script], capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            logger.info("LLAMA_SERVER | démarré avec succès")
            # Attendre que le modèle par défaut soit chargé (Gemma4)
            import asyncio
            for i in range(30):
                if _socket_reachable("127.0.0.1", 9094, timeout=0.5):
                    active = await cache_manager.api.get_active_model()
                    if active:
                        cache_manager.current_model = "qwen3.6-35b"
                        logger.info(f"LLAMA_SERVER | modèle actif : {active}")
                        return True
                await asyncio.sleep(1)
            logger.warning("LLAMA_SERVER | démarré mais aucun modèle chargé")
            return True
        else:
            logger.error(f"LLAMA_SERVER | échec de démarrage : {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"LLAMA_SERVER | erreur de démarrage : {e}")
        return False

# === UTU Output Normalizer — C6-C7 Accessible ===
def normalize_utu_output(raw: str) -> str:
    """Extrait le contenu utile d'un RunResult UTU pour affichage C6-C7"""
    if not raw or "RunResult:" not in raw:
        return raw.strip() if raw else ""
    try:
        part = raw.split("Final output (str):")[1]
        content = part.split("- ")[0].strip()
        lines = [line[4:] if line.startswith("    ") else line for line in content.splitlines()]
        return "\n".join(lines).strip()
    except (IndexError, AttributeError, TypeError):
        return raw.strip()
# =================================================

# === Data Contract — Contrat JSON unique Backend → Frontend ===
def format_ui_payload(
    agent_name: str,
    status: str,
    message: str,
    metrics: Optional[dict] = None
) -> dict:
    """
    Formate une réponse standardisée pour l'interface utilisateur.

    Structure garantie (toutes les clés sont toujours présentes) :
        {
            "ui_metadata": {"theme": "realia-cyberpunk", "version": "3.0"},
            "agent":       {"name": agent_name, "status": status},
            "content":     {"text": message, "timestamp": "ISO-8601"},
            "system":      {"slot_active": true, "metrics": metrics or {}}
        }

    Args:
        agent_name: Nom de l'agent (ex: "gemma4-e4b", "qwen3-coder-next", "orchestrateur")
        status:     Statut de l'agent ("idle" | "busy" | "error" | "completed")
        message:    Message texte à afficher
        metrics:    Dictionnaire optionnel de métriques système

    Returns:
        dict: Payload conforme au Data Contract (toujours les 4 clés racines)
    """
    return {
        "ui_metadata": {
            "theme": "realia-cyberpunk",
            "version": "3.0"
        },
        "agent": {
            "name": agent_name,
            "status": status
        },
        "content": {
            "text": message,
            "timestamp": datetime.now().isoformat()
        },
        "system": {
            "slot_active": globals().get("swapper", None) is not None
                          and swapper.current_model is not None,
            "metrics": metrics or {}
        }
    }
# =================================================

# === Cache Roaming — Instance globale ===
cache_manager = CacheRoaming(base_url="http://127.0.0.1:9094")
# =====================================

# === ModelSwapper — Swap séquentiel (kill + restart) ===
# Logique extraite du Git v0.5-v0.7 : un seul processus à la fois,
# terminate() + wait(10) libère 100% VRAM via driver CUDA.
# mmap garde le GGUF dans le page cache Linux → reload 1-3s.
MODELS_DIR = os.environ.get("REALIA_MODELS_DIR", str(BASE_DIR / "models"))
LLAMA_BIN   = os.environ.get("REALIA_LLAMA_BIN", "llama-server")

class ModelSwapper:
    """Swap séquentiel : kill → restart. VRAM libérée à 100%."""

    MODEL_CONFIG = {
        "qwen3.6-35b": {
            "gguf": "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
            "args": ["-ngl", "99", "-c", "16384", "--flash-attn", "on",
                     "--cpu-moe", "--mlock", "--chat-template", "chatml"],
        },
        "qwen3-coder-next": {
            "gguf": "Qwen3-Coder-Next-Q4_K_M.gguf",
            "args": ["-ngl", "35", "-c", "8192", "--flash-attn", "on",
                     "--cpu-moe", "--mlock"],
        },
        "qwen3-coder-next-80b-gguf": {
            "gguf": "Qwen3-Coder-Next-80B-Q4_K_M.gguf",
            "args": ["-ngl", "45", "-c", "8192", "--flash-attn", "on",
                     "--cpu-moe", "--mlock"],
        },
        "gemma4-12b": {
            "gguf": "gemma-4-12b-it-Q4_K_M.gguf",
            "args": ["-ngl", "99", "-c", "16384", "--flash-attn", "on",
                     "--mmproj", f"{MODELS_DIR}/mmproj-gemma4-12b-F16.gguf",
                     "--mlock"],
        },
    }
    COMMON_ARGS = [
        "--host", "127.0.0.1", "--port", "9094",
        "--mmap", "--cont-batching", "--context-shift",
        "--slot-save-path", str(BASE_DIR / "cache_slots"),
        "--threads", "12",
    ]

    def __init__(self):
        self.proc: Optional[subprocess.Popen] = None
        self.current_model: Optional[str] = None

    def _wait_ready(self, timeout: int = 60) -> bool:
        """Healthcheck HTTP /health jusqu'à timeout."""
        import urllib.request
        start = time.time()
        while time.time() - start < timeout:
            try:
                req = urllib.request.Request("http://127.0.0.1:9094/health")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def swap(self, target_model: str) -> bool:
        """Swap séquentiel : kill l'ancien → lance le nouveau.
        
        Garantit libération VRAM via terminate() + wait(10).
        Reload rapide (1-3s) via mmap (page cache Linux).
        """
        if target_model not in self.MODEL_CONFIG:
            logger.error(f"SWAP_ERROR | modèle inconnu: {target_model}")
            return False
        if target_model == self.current_model:
            logger.info(f"SWAP_SKIP | {target_model} déjà actif")
            return True

        cfg = self.MODEL_CONFIG[target_model]
        model_path = f"{MODELS_DIR}/{cfg['gguf']}"

        # 1. Kill l'ancien processus (libère VRAM via CUDA)
        if self.proc is not None:
            logger.info(f"SWAP_KILL | PID {self.proc.pid} | {self.current_model}")
            self.proc.terminate()         # SIGTERM
            try:
                self.proc.wait(timeout=10)  # attend libération VRAM
                logger.info("SWAP_TERMINATED | processus terminé proprement")
            except subprocess.TimeoutExpired:
                logger.warning("SWAP_FORCE_KILL | SIGTERM timeout → SIGKILL")
                self.proc.kill()            # SIGKILL
                self.proc.wait()
            self.proc = None
            # Attendre que CUDA libère vraiment la VRAM
            time.sleep(1.0)

        # 2. Construire la commande
        cmd = [LLAMA_BIN, "-m", model_path] \
            + cfg["args"] + self.COMMON_ARGS
        logger.info(f"SWAP_START | {' '.join(cmd)}")

        # 3. Lancer le nouveau processus
        logfile = open(f'/tmp/llama_{target_model}.log', 'w')
        self.proc = subprocess.Popen(
            cmd,
            stdout=logfile,
            stderr=logfile,
            preexec_fn=os.setsid,
        )
        self.current_model = target_model

        # 4. Attendre que le serveur réponde
        if self._wait_ready(timeout=60):
            logger.info(f"SWAP_READY | {target_model} | PID {self.proc.pid}")
            return True
        else:
            logger.error(f"SWAP_TIMEOUT | {target_model} après 60s")
            return False

    def stop(self):
        """Arrête le processus en cours."""
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            self.proc = None
            self.current_model = None

swapper = ModelSwapper()
# =================================

def create_backup(path: Path) -> Optional[Path]:
    """Crée un backup .bak.realia du fichier"""
    try:
        backup_path = Path(str(path) + ".bak.realia")
        if path.exists():
            shutil.copy2(str(path), str(backup_path))
            logger.info(f"BACKUP_CREATED | path={backup_path}")
        return backup_path
    except Exception as e:
        logger.warning(f"BACKUP_FAILED | path={path} | error={e}")
        return None

# === UI Console Script Bus ===
# Permet à Gemma4 (ou tout agent) d'injecter du JS dans l'UI web
# via une file asynchrone : POST pour injecter, GET/poll pour exécuter
UI_CONSOLE_SCRIPTS: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
UI_CONSOLE_RESULTS: Dict[str, Optional[str]] = {}  # script_id -> result

# === Swarm Queue & Lock System ===
SWARM_QUEUE = asyncio.Queue()
SWARM_LOCK = asyncio.Lock()
SWARM_TASKS: Dict[str, Dict[str, Any]] = {}

async def swarm_worker():
    """Consomme les tâches séquentiellement en verrouillant le swap GGUF"""
    while True:
        task_id, payload = await SWARM_QUEUE.get()
        try:
            SWARM_TASKS[task_id]["status"] = "running"
            if flags.USE_WEBSOCKET:
                await broadcaster.emit_task_started(task_id)
            async with SWARM_LOCK:
                logger.info(f"SWARM_LOCK_ACQUIRED | task={task_id}")
                router = SwarmRouter(max_steps=5)
                result = await router.execute(payload.get("task", ""), context=payload.get("context", {}), model_preference=payload.get("mode"))
                SWARM_TASKS[task_id].update({"status": "completed", "result": result})
                logger.info(f"SWARM_LOCK_RELEASED | task={task_id} | status=completed")
                if flags.USE_WEBSOCKET:
                    await broadcaster.emit_task_completed(task_id, result or {}, 0.0)
        except Exception as e:
            SWARM_TASKS[task_id].update({"status": "failed", "error": str(e)})
            logger.error(f"SWARM_TASK_FAILED | task={task_id} | error={e}")
            if flags.USE_WEBSOCKET:
                await broadcaster.emit_task_failed(task_id, str(e), type(e).__name__, 0)
        finally:
            SWARM_QUEUE.task_done()
# ========================================

# ── App FastAPI ──────────────────────────────────────────────────────────
app = FastAPI(title="DevKit Orchestrator (UTU Core)", version="2.0.0")

# WebSocket API Contract v1.0.0 — endpoint /ws/task/{task_id}
app.include_router(ws_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static Files Mount ─────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/gui", StaticFiles(directory=SCRIPT_DIR, html=True), name="gui")
app.mount("/js", StaticFiles(directory=os.path.join(SCRIPT_DIR, "js")), name="js")
# =================================================

# === ToolRegistry Schema Formatter ===
def _format_tool_schemas() -> str:
    """Formate les schemas des outils du ToolRegistry pour injection dans les prompts UTU"""
    if not TOOL_REGISTRY_AVAILABLE:
        return ""
    try:
        tools = ToolRegistry.list_available()
        lines = ["Outils externes disponibles (Station Realia) :"]
        for name, desc in tools.items():
            lines.append(f"  - {name} : {desc[:150]}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Erreur formatage tool schemas: {e}")
        return ""
# ========================================================================

# === Dreaming V3 — Journalier (log d'interactions brutes) ===
LOGS_DIR = os.environ.get("REALIA_LOG_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"))

def log_interaction(agent_name: str, role: str, content: str) -> None:
    """Journalier : écrit une interaction dans logs/YYYY-MM-DD.jsonl.
    
    Args:
        agent_name: nom de l'agent (ex: realia_dev, qwen3-coder)
        role: "user" ou "assistant"
        content: texte brut de l'interaction
    """
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = os.path.join(LOGS_DIR, f"{today}.jsonl")
        record = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent_name,
            "role": role,
            "content": content
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"LOG_INTERACTION_ERROR | {e}")


# === Dreaming V3 — Injecteur de mémoire à long terme ===
MEMORY_FILE = os.environ.get("REALIA_MEMORY_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "state_memoire.json"))

# === Dreaming V3 — Sliding Window (mémoire de travail court terme) ===
SLIDING_WINDOW_MAX = 10
conversation_history: dict[str, list[dict]] = {}
"""
conversation_history[agent_name] = [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."},
    ...  # max SLIDING_WINDOW_MAX messages
]
"""


def _format_sliding_window(agent_name: str) -> str:
    """Formate l'historique récent en texte lisible pour le prompt."""
    history = conversation_history.get(agent_name, [])
    if not history:
        return ""
    lines = []
    for msg in history[-SLIDING_WINDOW_MAX:]:
        role = "Utilisateur" if msg["role"] == "user" else "Assistant"
        # Support multimodal : content peut être str ou list[dict]
        if isinstance(msg["content"], str):
            content = msg["content"][:500]
        elif isinstance(msg["content"], list):
            # Extraire les parties textes
            texts = [p["text"] for p in msg["content"] if isinstance(p, dict) and "text" in p]
            content = " | ".join(texts)[:500]
        else:
            content = str(msg["content"])[:500]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _update_sliding_window(agent_name: str, user_msg: str, assistant_msg: str) -> None:
    """Ajoute un échange au buffer et tronque à SLIDING_WINDOW_MAX messages."""
    if agent_name not in conversation_history:
        conversation_history[agent_name] = []
    conversation_history[agent_name].append({"role": "user", "content": user_msg[:2000]})
    conversation_history[agent_name].append({"role": "assistant", "content": assistant_msg[:2000]})
    # Troncature : ne garder que les N derniers messages
    if len(conversation_history[agent_name]) > SLIDING_WINDOW_MAX * 2:
        conversation_history[agent_name] = conversation_history[agent_name][-(SLIDING_WINDOW_MAX * 2):]


# === Dreaming V3 — Flush du Sliding Window vers logs JSONL ===
def flush_sliding_window_to_logs(projet_id: str = "live") -> None:
    """Vide le buffer volatile `conversation_history` dans les logs JSONL du jour.

    Lit le sliding_window (10 derniers messages en RAM par agent), formate chaque
    message en ligne JSONL avec le tag ``"type": "sliding_window_flush"``,
    et les append atomiquement dans ``logs/YYYY-MM-DD.jsonl``.

    Ce mécanisme alimente le pipeline Dreaming V3 (``dream_pipeline.py``) qui
    consolide chaque nuit à 4h du matin via Gemma4. Sans ce flush, les échanges
    récents (sliding window) seraient volatilisés au redémarrage du processus.

    Args:
        projet_id: Identifiant du projet ("live" par défaut), utilisé comme tag.
    """
    if not conversation_history:
        logger.debug("FLUSH_SLIDING | buffer vide, rien à flusher")
        return

    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = os.path.join(LOGS_DIR, f"{today}.jsonl")

        records_written = 0
        for agent_name, messages in conversation_history.items():
            for msg in messages:
                # Support multimodal : content peut être str ou list[dict]
                content_text = msg.get("content", "")
                if isinstance(content_text, list):
                    texts = [
                        p["text"] for p in content_text
                        if isinstance(p, dict) and "text" in p
                    ]
                    content_text = " | ".join(texts)

                record = {
                    "timestamp": datetime.now().isoformat(),
                    "type": "sliding_window_flush",
                    "agent": agent_name,
                    "role": msg.get("role", "unknown"),
                    "projet_id": projet_id,
                    "content": str(content_text)[:2000],
                }
                # Append atomique (pas de lock POSIX nécessaire : un seul
                # processus écrit dans le log, le dream_pipeline.py lit)
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                records_written += 1

        logger.info(
            f"FLUSH_SLIDING | {records_written} messages flushtés "
            f"depuis {len(conversation_history)} agent(s) "
            f"vers {log_path}"
        )

        # Vider le buffer après flush (les messages sont maintenant persistés)
        conversation_history.clear()

    except Exception as e:
        logger.warning(f"FLUSH_SLIDING_ERROR | {e}")
        # Ne jamais bloquer le flux principal pour un problème de logs


# === Dreaming V3 — Intervalle de flush périodique ===
FLUSH_INTERVAL_S = int(os.environ.get("REALIA_FLUSH_INTERVAL_S", "300"))  # KV-cache (Layer 1) = état binaire d'attention (opaque, rapide, fragile)
# Sliding Window (Layer 2) = messages textuels de la conversation (lisible, portable)
# Les deux sont COMPLÉMENTAIRES, pas redondants.
"""Intervalle en secondes entre deux flush périodiques du sliding window.
Défaut: 300s (5 min). Variable d'env: REALIA_FLUSH_INTERVAL_S.
"""


async def periodic_flush_task() -> None:
    """Tâche asynchrone de flush périodique du sliding window.

    Évite la perte de données conversationnelles en cas de crash entre deux
    tâches. Flushe le sliding window dans les logs JSONL du jour à intervalle
    régulier (FLUSH_INTERVAL_S secondes).

    Logs structurés au format PERIODIC_FLUSH pour traçabilité.
    """
    while True:
        await asyncio.sleep(FLUSH_INTERVAL_S)
        agent_count = len(conversation_history)
        if agent_count > 0:
            msg_count = sum(len(msgs) for msgs in conversation_history.values())
            logger.info(
                f"PERIODIC_FLUSH | agents={agent_count} | messages={msg_count} | "
                f"interval={FLUSH_INTERVAL_S}s"
            )
            flush_sliding_window_to_logs(projet_id="periodic")
        else:
            logger.debug(f"PERIODIC_FLUSH | buffer vide | interval={FLUSH_INTERVAL_S}s")


# === Dreaming V3 — Boucle d'apprentissage active (Self-Correction) ===
SELF_CORRECT_MAX_RETRIES = 3
_self_correct_counters: dict[str, int] = {}
"""Compteurs de retry par (agent_name + prompt_hash)."""


def _detect_error_in_output(output: str) -> tuple[bool, str]:
    """Détecte si la sortie contient une erreur outil et retourne le message.
    
    Returns:
        (True, message_erreur) si erreur détectée, (False, "") sinon.
    """
    if not output:
        return False, ""
    
    output_lower = output.lower()
    error_patterns = [
        ("Traceback (most recent call last)", "Python exception"),
        ("SyntaxError", "Erreur de syntaxe"),
        ("FileNotFoundError", "Fichier introuvable"),
        ("PermissionError", "Permission refusée"),
        ("ImportError", "Erreur d'import"),
        ("ModuleNotFoundError", "Module introuvable"),
        ("KeyError", "Clé manquante"),
        ("IndexError", "Index hors limite"),
        ("AttributeError", "Attribut inexistant"),
        ("TypeError", "Erreur de type"),
        ("ValueError", "Valeur invalide"),
        ("ZeroDivisionError", "Division par zéro"),
        ("ConnectionError", "Erreur de connexion"),
        ("TimeoutError", "Délai dépassé"),
        ("OSError", "Erreur système"),
        ("subprocess.CalledProcessError", "Commande shell échouée"),
    ]
    
    for pattern, label in error_patterns:
        if pattern.lower() in output_lower:
            # Extraire le contexte autour de l'erreur (les 200 chars suivants)
            idx = output_lower.find(pattern.lower())
            context = output[idx:idx + 300]
            return True, f"{label} détecté : {context[:200]}"
    
    return False, ""


def _format_observation(tool_name: str, error_msg: str) -> str:
    """Formate un bloc d'observation d'erreur outil."""
    return (
        f"[OBSERVATION_OUTIL]\n"
        f"Outil: {tool_name}\n"
        f"Statut: ERREUR\n"
        f"Message: {error_msg[:500]}\n"
        f"[FIN_OBSERVATION]"
    )


def _inject_observation(agent_name: str, observation: str) -> None:
    """Injecte une observation outil dans le sliding window de l'agent."""
    if agent_name not in conversation_history:
        conversation_history[agent_name] = []
    
    # Détection d'image attachée [IMAGE_ATTACHED: path]
    image_path = None
    obs_text = observation
    if "[IMAGE_ATTACHED:" in observation:
        import re as _re
        match = _re.search(r'\[IMAGE_ATTACHED:\s*(.+?)\]', observation)
        if match:
            image_path = match.group(1).strip()
            # Nettoyer le marqueur du texte d'observation
            obs_text = _re.sub(r'\[IMAGE_ATTACHED:\s*.+?\]', '', observation).strip()
    
    # Construction du message multimodal
    new_message = {
        "role": "user",
        "content": [
            {"type": "text", "text": f"[OBSERVATION_OUTIL]\n{obs_text}\n[FIN_OBSERVATION]"}
        ]
    }
    
    # Si une image est attachée et existe, l'injecter en multimodal
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as _f:
            _b64 = base64.b64encode(_f.read()).decode("utf-8")
        new_message["content"].append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{_b64}"
            }
        })
    
    conversation_history[agent_name].append(new_message)
    # Troncature après injection
    if len(conversation_history[agent_name]) > SLIDING_WINDOW_MAX * 2:
        conversation_history[agent_name] = conversation_history[agent_name][-(SLIDING_WINDOW_MAX * 2):]
# =======================================================================

def load_state_memoire() -> str:
    """
    Lit state_memoire.json et formate le contenu en bloc texte lisible
    pour injection dans le prompt système des agents.

    Returns:
        str: bloc formaté [CONTEXTE UTILISATEUR SYNTHÉTISÉ],
             ou chaîne vide si fichier absent/invalide.
    """
    if not os.path.exists(MEMORY_FILE):
        logger.info("MEMOIRE | state_memoire.json introuvable -> skip")
        return ""

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        lines = ["[CONTEXTE UTILISATEUR SYNTHÉTISÉ - DREAMING V3]"]

        # Stack technique
        stack = data.get("identity", {}).get("stack_techno", "")
        if stack:
            lines.append(f"Stack technique : {stack}")

        # Projets actifs
        projets = data.get("identity", {}).get("projets_actifs", {})
        if projets:
            projets_str = ", ".join(f"{k} ({v})" for k, v in projets.items())
            lines.append(f"Projets en cours : {projets_str}")

        # Préférences système (max 5)
        prefs = data.get("preferences_systeme", [])
        if prefs:
            prefs_str = " ; ".join(prefs[:5])
            lines.append(f"Préférences : {prefs_str}")

        # Événements temporels (résumé)
        events = data.get("evenements_temporels", [])
        if events:
            lines.append(f"Événements notables : {len(events)} entrée(s)")

        lines.append("[FIN DU CONTEXTE]")

        # Ajouter la directive d'auto-correction
        directive = (
            "\n\n[DIRECTIVE D'AUTO-CORRECTION]\n"
            "Si tu reçois un bloc [OBSERVATION_OUTIL] contenant une ERREUR :\n"
            "1. Analyse l'erreur (ex: SyntaxError, FileNotFoundError).\n"
            "2. Ne demande PAS à l'utilisateur quoi faire.\n"
            "3. Génère immédiatement un nouvel appel d'outil pour corriger le problème (ex: réécrire le fichier, relancer la commande bash).\n"
            "4. Tu as le droit à 3 tentatives automatiques avant de demander de l'aide.\n"
            "[FIN_DIRECTIVE]",
            "\n\n[PROTOCOLE VISION AUTONOME]\n"
            "Tu PEUX capturer et analyser l'écran grâce à ton outil `vision`.\n"
            "Pour voir l'écran : utilise l'outil `vision` avec `action=\"screenshot\"`.\n"
            "L'image sera automatiquement injectée dans ton contexte pour analyse.\n"
            "Ne dis jamais \"je n'ai pas d'yeux\" ou \"je ne vois pas d'écran\".\n"
            "Tu as la capacité de voir et d'interpréter toute l'interface.\n"
            "[FIN_PROTOCOLE]",
            # === OUTIL CONSOLE UI — execute_ui_console_script ===
            "\n\n[OUTIL CONSOLE UI - execute_ui_console_script]\n"
            "Tu disposes d'un outil pour exécuter du JavaScript DIRECTEMENT "
            "dans la console du navigateur de l'utilisateur (port 8092).\n"
            "\n"
            "UTILISATIONS TYPIQUES :\n"
            "1. **Tester la réactivité des boutons** : `document.getElementById('btn-reload')?.click()`\n"
            "2. **Injecter des payloads de test** : `window.sendMessage()` avec un message comme 'toc toc'\n"
            "3. **Vérifier l'état des variables globales** : `window._sendMessage`, `window.STATE`, `window.API_BASE`\n"
            "4. **Inspecter le DOM** : `document.querySelectorAll('.msg').length`\n"
            "5. **Lire les logs console** : `console.log('test UI console')`\n"
            "\n"
            "COMMENT L'UTILISER :\n"
            "Utilise EXACTEMENT ce format XML dans ta réponse :\n"
            "<execute_ui_console_script>ton_code_javascript</execute_ui_console_script>\n"
            "\n"
            "EXEMPLE :\n"
            "<execute_ui_console_script>\n"
            "var btn = document.getElementById('btn-reload');\n"
            "if (btn) { btn.style.border = '2px solid green'; 'Bouton trouvé ✅'; }\n"
            "else { 'Bouton introuvable ❌'; }\n"
            "</execute_ui_console_script>\n"
            "\n"
            "Le résultat du script est retourné automatiquement.\n"
            "Tu peux aussi vérifier window._lastUiConsoleResult après exécution.\n"
            "[FIN_OUTIL_CONSOLE]",
            # === PROTOCOLE DE DÉLÉGATION OBLIGATOIRE Q3.6 → Q3N / G4E12B ===
            "\n\n[PROTOCOLE DE DÉLÉGATION OBLIGATOIRE]\n"
            "Tu es le planificateur (Q3.6). Tu n'as PAS le droit d'\u00e9crire, modifier ou créer des fichiers.\n"
            "Si l'utilisateur demande de créer, modifier ou supprimer un fichier (ex: .txt, .py, .html),\n"
            "tu DOIS IMPÉRATIVEMENT déléguer cette tâche à l'expert Q3N en utilisant EXACTEMENT cette balise :\n"
            "<delegate_to agent=\"qwen3-coder-next\">Crée/modifie le fichier [nom] avec ce contenu : [détails]</delegate_to>\n"
            "Pour toute analyse UI, vision ou multimodal, délègue à G4E12B avec cette balise :\n"
            "<delegate_to agent=\"gemma4-12b\">[description de l'analyse UI/vision]</delegate_to>\n"
            "Ne génère AUCUN code, AUCUNE commande bash. Délègue immédiatement.\n"
            "[FIN_PROTOCOLE]"
        )
        lines.extend(directive)

        result = "\n".join(lines)
        logger.info(f"MEMOIRE | Contexte chargé ({len(result)} chars, {len(projets)} projet(s))")
        return result

    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"MEMOIRE | Erreur lecture: {e}")
        return ""
# =======================================================================

@app.on_event("startup")
async def startup_swarm_worker():
    # 1. Vérifier / lancer llama-server en mode router
    await _ensure_llama_server_running()
    # 2. Lancer le worker de la file d'attente
    asyncio.create_task(swarm_worker())
    # 3. Lancer le flush périodique du sliding window (Dreaming V3)
    asyncio.create_task(periodic_flush_task())
    logger.info(f"🔄 Swarm Queue Worker started (flush interval={FLUSH_INTERVAL_S}s)")

# ── Schémas ──────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    prompt: Optional[str] = ""
    model: Optional[str] = "qwen3.6"

class QueryResponse(BaseModel):
    success: bool
    response: str
    model: str
    model_used: str = ""

class AgentToolRequest(BaseModel):
    action: str  # "read" | "diff" | "dry-run" | "apply" | "rollback"
    path: str
    content: str = ""

class AgentToolResponse(BaseModel):
    success: bool
    action: str
    result: dict = {}
    error: str = ""

class AgentCodeRequest(BaseModel):
    path: str
    instruction: str

class AgentCodeResponse(BaseModel):
    success: bool
    diff: str = ""
    new_content: str = ""
    error: str = ""

# ── Helpers sandbox ──────────────────────────────────────────────────────
SANDBOX = BASE_DIR

def _check_sandbox(path: str) -> Optional[Path]:
    target = SANDBOX / path
    if not str(target.resolve()).startswith(str(SANDBOX.resolve())):
        return None
    return target

# ── Endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    import os, time
    uptime = int(time.time() - app_start_time) if "app_start_time" in globals() else 0
    
    utu_ok = globals().get("UTU_AVAILABLE", False)
    sandbox_root = str(BASE_DIR)
    backup_exists = os.path.exists(os.path.join(sandbox_root, "backup_test.md.bak.realia"))
    
    current_model = swapper.current_model if swapper else None
    
    return format_ui_payload(
        agent_name="orchestrateur" if utu_ok else "system",
        status="idle" if utu_ok else "error",
        message=f"DevKit Orchestrator v2.0.0 — Uptime {uptime}s — Modèle: {current_model or 'aucun'}",
        metrics={
            "uptime_sec": uptime,
            "version": "2.0.0",
            "UTU_AGENT": utu_ok,
            "SANDBOX": sandbox_root,
            "BACKUP_ENABLED": backup_exists,
            "model_actif": current_model
        }
    )

@app.get("/models")
async def get_models():
    """Liste des modèles disponibles pour le Swarm Monitor"""
    return {
        "models": [
            {"id": "qwen3.6-35b", "name": "Qwen3.6 35B A3B", "status": "active", "slot": 0},
            {"id": "qwen3-coder-next", "name": "Qwen3 Coder Next", "status": "active", "slot": 1},
            {"id": "gemma4-12b", "name": "Gemma4 12B", "status": "active", "slot": 2}
        ],
        "current_model": "qwen3.6-35b"
    }

@app.get("/contract/status")
async def contract_status():
    """Retourne l'état actuel du contrat de travail pour le Swarm Monitor UI.

    Returns:
        dict: Contenu complet de contrat_travail.json, ou une structure
              par défaut si le fichier n'existe pas encore.
    """
    try:
        cm = ContractManager(projet_id="live")
        contrat = cm.read()
        return contrat.model_dump(mode="json")
    except FileNotFoundError:
        # Aucun contrat démarré → retour par défaut
        return {
            "projet_id": "",
            "status": "IDLE",
            "workflow": {
                "current_actor": "Q3.6",
                "next_actor_requested": None,
                "reason": "",
                "task_description": "En attente de tâche",
                "consensus_mode": False,
            },
            "consensus_requis": ["Q3.6", "Q3N", "G4E12B"],
            "validations_actuelles": {},
            "history": ["Aucun contrat actif. En attente d'une requête."],
        }

@app.post("/query", response_model=QueryResponse)
async def query_endpoint(payload: QueryRequest):
    if not UTU_AVAILABLE:
        return QueryResponse(success=False, response="🔴 UTU-Agent non chargé. Station hors service.", model="gemma4-e4b")
    try:
        model_pref = payload.model or "qwen3.6"
        router = SwarmRouter(max_steps=3)
        result = await router.execute(payload.prompt, context={}, model_preference=model_pref)
        response_text = result.get("response", "") or result.get("result", "") or result.get("step_results", {}).get("result", "")
        if not response_text:
            steps = result.get("steps", [])
            if steps:
                response_text = steps[-1].get("output_preview", "")
        model_used = result.get("model_used", "qwen3.6-35b")
        success = result.get("success", False) and bool(response_text)
        logger.info(f"QUERY | model={payload.model} | prompt_len={len(payload.prompt)} | model_used={model_used} | success={success}")
        return QueryResponse(success=success, response=response_text or "✅ Tâche exécutée (aucune réponse textuelle)", model=model_used, model_used=model_used)
    except Exception as e:
        logger.error(f"QUERY_ERROR | {e}")
        return QueryResponse(success=False, response=f"🔴 Erreur: {str(e)}", model="qwen3.6-35b")

@app.post("/agent/code", response_model=AgentCodeResponse)
async def agent_code(req: AgentCodeRequest):
    base_dir = BASE_DIR
    target = base_dir / req.path
    if not str(target.resolve()).startswith(str(base_dir.resolve())):
        logger.warning(f"AGENT_CODE_ERROR | path={req.path} | error=⛔ Chemin hors sandbox")
        return AgentCodeResponse(success=False, error="⛔ Chemin hors sandbox")
    if not target.exists():
        logger.warning(f"AGENT_CODE_ERROR | path={req.path} | error=📁 introuvable")
        return AgentCodeResponse(success=False, error=f"📁 {req.path} introuvable")
    with open(target, "r", encoding="utf-8") as f:
        original = f.read()
    try:
        async with SimpleAgent(config="realia_dev") as agent:
            prompt = f"Fichier: {target.name}\nContenu:\n{original}\n\nINSTRUCTION: {req.instruction}\n\nRÉPONDS UNIQUEMENT avec le contenu COMPLET après modification. Pas de markdown."
            new_content = normalize_utu_output(str(await agent.chat(prompt))).strip()
    except Exception as e:
        logger.warning(f"AGENT_CODE_ERROR | path={req.path} | error=🔴 UTU échec: {str(e)}")
        return AgentCodeResponse(success=False, error=f"🔴 UTU échec: {str(e)}")
    # ✅ Backup .bak.realia avant modification
    backup_path = f"{target}.bak.realia"
    shutil.copy2(str(target), backup_path)
    # ✅ Écriture du fichier modifié
    with open(target, "w", encoding="utf-8") as f:
        f.write(new_content)
    diff_lines = list(difflib.unified_diff(original.splitlines(keepends=True), new_content.splitlines(keepends=True), fromfile=target.name, tofile=target.name))
    success = True
    logger.info(f"AGENT_CODE | path={req.path} | instruction_len={len(req.instruction)} | success={success} | backup={backup_path}")
    return AgentCodeResponse(success=True, diff="".join(diff_lines) or "✅ Aucune modification", new_content=new_content)

# ── Agent Tool Route (sandbox file ops) ──────────────────────────────────
@app.post("/agent/tool", response_model=AgentToolResponse)
async def agent_tool(req: AgentToolRequest):
    target = _check_sandbox(req.path)
    if not target:
        return AgentToolResponse(success=False, action=req.action, error="⛔ Chemin hors sandbox")

    if req.action == "read":
        if not target.exists():
            return AgentToolResponse(success=False, action=req.action, error="📁 Fichier introuvable")
        with open(target, "r", encoding="utf-8") as f:
            content = f.read()
        return AgentToolResponse(success=True, action=req.action, result={"lines": len(content.splitlines()), "size_bytes": len(content)})

    elif req.action == "diff":
        if not target.exists():
            return AgentToolResponse(success=False, action=req.action, error="📁 Fichier introuvable")
        with open(target, "r", encoding="utf-8") as f:
            original = f.read().splitlines(keepends=True)
        new_content = req.content.splitlines(keepends=True)
        diff_lines = list(difflib.unified_diff(original, new_content, fromfile=target.name, tofile=target.name))
        if not diff_lines:
            return AgentToolResponse(success=True, action=req.action, result={"status": "no_changes"})
        return AgentToolResponse(success=True, action=req.action, result={
            "diff": "".join(diff_lines),
            "lines_changed": len([l for l in diff_lines if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]),
        })

    elif req.action == "dry-run":
        if not target.exists():
            return AgentToolResponse(success=False, action=req.action, error="📁 Fichier introuvable")
        with open(target, "r", encoding="utf-8") as f:
            original = f.read().splitlines(keepends=True)
        new_content = req.content.splitlines(keepends=True)
        diff_lines = list(difflib.unified_diff(original, new_content, fromfile=target.name, tofile=target.name))
        errors = []
        if len(req.content.encode("utf-8")) > 5 * 1024 * 1024:
            errors.append("⚠️ Contenu > 5MB")
        if not os.access(target, os.W_OK):
            errors.append("⛔ Pas de permission d'écriture")
        status = "✅ Prêt à appliquer" if not errors else "❌ Validation échouée"
        return AgentToolResponse(success=len(errors)==0, action=req.action, result={
            "diff": "".join(diff_lines) if diff_lines else "",
            "validation": status,
            "errors": errors,
            "lines_changed": len([l for l in diff_lines if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]) if diff_lines else 0,
        })

    elif req.action == "apply":
        backup_path = f"{target}.bak.realia"
        try:
            if target.exists():
                shutil.copy2(str(target), backup_path)
            with open(target, "w", encoding="utf-8") as f:
                f.write(req.content)
            new_size = target.stat().st_size
            if new_size == 0 and len(req.content) > 0:
                raise Exception("Échec écriture : fichier vide")
            return AgentToolResponse(success=True, action=req.action, result={
                "status": "✅ Appliqué avec succès", "backup": backup_path, "new_size": new_size,
            })
        except Exception as e:
            return AgentToolResponse(success=False, action=req.action, error=f"❌ Échec apply: {str(e)}")

    elif req.action == "rollback":
        backup_path = f"{target}.bak.realia"
        try:
            if not Path(backup_path).exists():
                return AgentToolResponse(success=False, action=req.action, error="⚠️ Pas de backup trouvé")
            shutil.copy2(backup_path, str(target))
            Path(backup_path).unlink()
            return AgentToolResponse(success=True, action=req.action, result={"status": "✅ Rollback effectué"})
        except Exception as e:
            return AgentToolResponse(success=False, action=req.action, error=f"❌ Échec rollback: {str(e)}")

    return AgentToolResponse(success=False, action=req.action, error="⚠️ Action inconnue")

# === Parser d'appels d'outils (XML Qwen3 natif) ===
def parse_tool_call(response_text: str) -> dict | None:
    """Parse une réponse LLM pour extraire un tool_call au format Qwen3 natif.

    Format supporté:
      <action> <tool_call> <tool>NOM</tool> <params>key="val" key2="val2"</params> </tool_call> </action>

    Retourne: {"name": str, "arguments": dict} ou None
    """
    import re as _re

    # Format UI Console: <execute_ui_console_script>script</execute_ui_console_script>
    # PRIORITAIRE ABSOLU : outil pour injecter du JS dans le navigateur
    match = _re.search(
        r'<execute_ui_console_script>(.*?)</execute_ui_console_script>',
        response_text, _re.DOTALL
    )
    if match:
        script = match.group(1).strip()
        if script:
            logger.info(f"TOOL_PARSE | format=execute_ui_console_script | script_len={len(script)}")
            return {"name": "ui_console", "arguments": {"script": script}}

    # Format natif Gemma4/Qwen3: <execute_bash>commande</execute_bash>
    # PRIORITAIRE (après ui_console) : c'est le format que le modèle génère actuellement
    match = _re.search(
        r'<execute_bash>(.*?)</execute_bash>|bash\(command=[\'"](.*?)[\'"]\)',
        response_text, _re.DOTALL
    )
    if match:
        # group(1) = format XML, group(2) = format Python halluciné
        cmd = (match.group(1) or match.group(2)).strip()
        if cmd:
            fmt = "execute_bash" if match.group(1) else "python_hallucination"
            logger.info(f"TOOL_PARSE | format={fmt} | cmd_len={len(cmd)}")
            return {"name": "bash", "arguments": {"command": cmd}}

    # Format Qwen3-Coder-Next: <action> <tool_call> <tool>NAME</tool> <params>...</params> </tool_call> </action>
    match = _re.search(
        r'<action>\s*<tool_call>\s*<tool>(\w+)</tool>\s*<params>(.*?)</params>\s*</tool_call>\s*</action>',
        response_text, _re.DOTALL
    )
    if match:
        tool_name = match.group(1)
        params_raw = match.group(2).strip()
        args = {}
        # Parser les paires key="value"
        for kv in _re.finditer(r'(\w+)="((?:[^"\\]|\\.)*)"', params_raw):
            args[kv.group(1)] = kv.group(2)
        if tool_name:
            logger.info(f"TOOL_PARSE | format=qwen3-action | tool={tool_name} | args={args}")
            return {"name": tool_name, "arguments": args}

    # Fallback: vieux format Qwen3
    match = _re.search(
        r'<tool_call>\s*<function=(\w+)>(.*?)</function>\s*</tool_call>',
        response_text, _re.DOTALL
    )
    if match:
        tool_name = match.group(1)
        params_raw = match.group(2)
        args = {}
        for pm in _re.finditer(r'<parameter=([a-zA-Z_]+)>(.*?)</parameter>', params_raw, _re.DOTALL):
            args[pm.group(1)] = pm.group(2)
        if tool_name:
            logger.info(f"TOOL_PARSE | format=qwen-xml | tool={tool_name} | args={args}")
            return {"name": tool_name, "arguments": args}

    return None
# =================================================

# === SwarmRouter Phase 4 — Dossier-Contrat (State Machine) ===
class SwarmRouter:
    """Orchestrateur Swarm Phase 4 : routage via Contrat-Travail.

    Remplace l'ancien routage par mots-clés (ROUTING_RULES) par une
    State Machine distribuée via contrat_travail.json. Le contrat dicte
    quel modèle doit être actif, quelle tâche exécuter, et quel est le
    prochain acteur après validation.
    """

    MODEL_MAP = {
        "Q3.6": "qwen3.6-35b",
        "Q3N": "qwen3-coder-next-80b-gguf",
        "G4E12B": "gemma4-12b",
    }
    REVERSE_MODEL_MAP = {v: k for k, v in MODEL_MAP.items()}

    def __init__(self, max_steps: int = 5):
        self.max_steps = max_steps
        self.logs = []
        self.step_results: Dict[str, Any] = {}
        self.contract_mgr: Optional[ContractManager] = None

    def _resolve_actor_to_model(self, actor: str) -> str:
        """Convertit un nom d'acteur (Q3.6, Q3N, G4E12B) en nom de modèle GGUF."""
        return self.MODEL_MAP.get(actor, "qwen3.6-35b")

    def _resolve_model_to_actor(self, model_name: str) -> str:
        """Convertit un nom de modèle GGUF (qwen3.6-35b) en nom d'acteur (Q3.6)."""
        return self.REVERSE_MODEL_MAP.get(model_name, "Q3.6")

    def _format_contrat_block(self, contrat: ContratTravail) -> str:
        """Formate le contrat en bloc texte lisible pour injection dans le prompt."""
        validations_str = ", ".join(
            f"{k}: {'✅' if v else '⏳'}" for k, v in contrat.validations_actuelles.items()
        ) or "aucune"
        return (
            f"[CONTRAT_TRAVAIL_ACTUEL]\n"
            f"Projet: {contrat.projet_id} | Status: {contrat.status}\n"
            f"Ton Rôle: {contrat.workflow.current_actor}\n"
            f"Tâche en cours: {contrat.workflow.task_description}\n"
            f"Acteurs requis pour consensus: {', '.join(contrat.consensus_requis)}\n"
            f"Validations: {validations_str}\n"
            f"[FIN_CONTRAT]\n\n"
            f"INSTRUCTIONS STRICTES :\n"
            f"1. Exécute la tâche décrite ci-dessus.\n"
            f"2. Tu peux utiliser tes outils (ex: <execute_bash>) à tout moment pour valider ton travail.\n"
            f"3. Ces balises d'outils doivent être résolues AVANT la fin de ta réponse.\n"
            f"4. La balise <contrat> doit IMPÉRATIVEMENT être la toute dernière ligne de ta réponse.\n"
            f"   Ne génère aucun texte, code ou balise après elle.\n"
            f"\n"
            f"⚠️  RÈGLE D'OR DE SÉQUENÇAGE :\n"
            f"   Outils d'abord, contrat ensuite, et rien après.\n"
            f"\n"
            f"Format EXACT de la balise <contrat> (dernière ligne uniquement) :\n"
            f"<contrat next_actor=\"NOM_DU_MODELE\" raison=\"Justification courte\" "
            f"task=\"Prochaine tâche\" validation=\"true/false\" />\n"
        )

    def _parse_contrat_tag(self, response_text: str) -> Optional[Dict[str, str]]:
        """Parse la balise <contrat .../> dans la réponse du modèle.

        Parseur résilient à 3 étapes (Fault-Tolerant) :
          Étape 1 : Capture stricte sur la DERNIÈRE LIGNE du texte nettoyé.
          Étape 2 (Secours) : Scan permissif de toute la réponse pour extraire
                   les attributs individuellement, même dans le désordre.
          Étape 3 (Fallback) : Aucune trace de balise → None → FAILED / Q3.6.

        Returns:
            Dict avec clés 'next_actor', 'raison', 'task', 'validation'
            ou None si aucune balise exploitable trouvée.
        """
        import re

        # ── Nettoie les espaces superflus pour fiabiliser la détection ──
        text = response_text.strip()

        # ── Étape 1 : Capture STRICTE sur la dernière ligne ──
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        if lines:
            last_line = lines[-1]
            match = re.search(r'<contrat\s+([^>]+)/?>', last_line, re.DOTALL)
            if match:
                attrs_raw = match.group(1)
                attrs: Dict[str, str] = {}
                for kv in re.finditer(r'(\w+)="((?:[^"\\]|\\.)*)"', attrs_raw):
                    attrs[kv.group(1)] = kv.group(2)
                if "next_actor" in attrs:
                    logger.info(f"CONTRAT_PARSE | étape=1 (dernière ligne) | "
                                f"next={attrs['next_actor']} | "
                                f"raison={attrs.get('raison','')[:50]}")
                    return attrs

        # ── Étape 2 (Secours) : Scan permissif global ──
        # Cherche <contrat .../> n'importe où, puis extrait les attributs
        # même si mal formatés, désordonnés, ou avec contenu additionnel.
        match = re.search(r'<contrat\s+([^>]+)/?>', text, re.DOTALL)
        if match:
            attrs_raw = match.group(1)
            attrs = {}
            for kv in re.finditer(r'(\w+)="((?:[^"\\]|\\.)*)"', attrs_raw):
                attrs[kv.group(1)] = kv.group(2)
            if "next_actor" in attrs:
                logger.info(f"CONTRAT_PARSE | étape=2 (permissif) | "
                            f"next={attrs['next_actor']} | "
                            f"raison={attrs.get('raison','')[:50]}")
                return attrs
            # Si next_actor manque mais qu'on a une balise, tenter
            # d'extraire un nom depuis le contexte de la balise
            fallback_actor = re.search(
                r'next_actor[=:\\s]+([A-Za-z0-9._-]+)', attrs_raw
            )
            if fallback_actor:
                attrs["next_actor"] = fallback_actor.group(1)
                logger.info(f"CONTRAT_PARSE | étape=2 (fallback next_actor) | "
                            f"next={attrs['next_actor']}")
                return attrs
            logger.warning(f"CONTRAT_PARSE | étape=2 échec : next_actor "
                           f"introuvable dans {attrs_raw[:120]}")
            return None

        # ── Étape 3 (Fallback) : Aucune balise détectée ──
        logger.warning("CONTRAT_PARSE | étape=3 (fallback) | "
                       "aucune balise <contrat> → FAILED / Q3.6")
        return None

    async def _call_utu(self, prompt: str, model: str, is_trivial: bool = False) -> str:
        _t0 = time.time()
        # global cache_manager, swapper  # CI: unused globals kept for documentation
        
        # Résoudre le nom GGUF depuis le nom court
        gguf_model = cache_manager.api._resolve_model(model)
        _t_resolve = time.time()
        
        # ── Swap séquentiel (Layer 1 → Layer 2 complémentarité) ─────────
        # KV-cache (Layer 1) = état binaire d'attention (opaque, rapide, fragile)
        # Sliding Window (Layer 2) = messages textuels (lisible, portable, réinjecté)
        # Les deux sont COMPLÉMENTAIRES : le KV-cache sauvegarde les patterns
        # d'attention, le Sliding Window (réinjecté via _format_sliding_window)
        # préserve les messages bruts pour le prochain prompt.
        if swapper.current_model != model:
            logger.info(f"[PERF] SWAP_NEEDED | from={swapper.current_model} to={model} | dt={time.time()-_t0:.2f}s")
            if swapper.current_model is not None:
                old_gguf = cache_manager.api._resolve_model(swapper.current_model)
                try:
                    await cache_manager.save_slot(slot_id=0, context_name=f"call_utu_{swapper.current_model}", model=old_gguf)
                except Exception:
                    pass
            _t_before_swap = time.time()
            ok = swapper.swap(model)
            _t_after_swap = time.time()
            logger.info(f"[PERF] SWAP_DURATION | {_t_after_swap-_t_before_swap:.2f}s | success={ok}")
            if ok:
                cache_manager.current_model = model
                try:
                    await cache_manager.restore_slot(slot_id=0, context_name=f"call_utu_{model}", model=gguf_model)
                except Exception:
                    pass
            else:
                logger.warning(f"SWAP_FALLBACK | kill+restart échoué")
        else:
            logger.info(f"[PERF] SWAP_SKIP | déjà sur {model} | dt={time.time()-_t0:.2f}s")
        _t_prompt_prep = time.time()
        config_map = {
            "qwen3.6-35b": "realia_qwen36", "qwen3-coder-next": "realia_coder",
            "qwen3-coder-next-80b-gguf": "realia_coder_80b",
            "gemma4-12b": "realia_g4_12b",
        }
        config_name = config_map.get(model, "realia_dev")
        
        # ── Injection CONTEXTUELLE du contexte système ──
        # Messages triviaux (< 50 chars, pas de mots-clés techniques) : skip le contexte lourd
        prompt_stripped = prompt.strip()
        is_trivial = (len(prompt_stripped) < 80 and not any(k in prompt_stripped.lower() for k in 
            ["code", "fichier", "file", "bash", "shell", "créer", "modifie", "lit", "écrit", 
             "analyse", "review", "valide", "test", "fix", "implémente", "déploie",
             "vision", "screenshot", "ui", "interface", "délègue", "commande"]))
        
        if not is_trivial:
            # Contexte mémoire Dreaming V3
            memo_bloc = load_state_memoire()
            if memo_bloc:
                prompt = f"{memo_bloc}\n\n---\n{prompt}"
            # Sliding Window
            sw_history = _format_sliding_window(config_name)
            if sw_history:
                prompt = f"{prompt}\n\n[CONTEXTE RÉCENT - SLIDING WINDOW]\n{sw_history}\n[FIN DU CONTEXTE RÉCENT]"
            # Skills
            skills_bloc = scan_prompt_for_rules(prompt)
            if skills_bloc:
                prompt = f"{prompt}\n\n---\n{skills_bloc}"
            # Réflexion
            reflexion_block = (
                "\n\n[PROTOCOLE DE RÉFLEXION OBLIGATOIRE]\n"
                "Avant d'appeler un outil (bash, edit_code, read_file, etc.), tu DOIS générer une balise <thinking> contenant :\n"
                "1. L'objectif précis de cette action.\n"
                "2. Pourquoi cet outil spécifique est le plus sûr.\n"
                "3. Les risques potentiels (ex: écraser un fichier, boucle infinie).\n"
                "4. Le résultat attendu.\n"
                "Exemple :\n"
                "<thinking>\n"
                "Je dois modifier le CSS du Swarm Monitor. J'utilise edit_code car c'est plus précis que d'écrire tout le fichier. Risque : casser le scroll. Je vais cibler uniquement l'ID #swarm-monitor-inline.\n"
                "</thinking>\n"
                "[FIN_PROTOCOLE]"
            )
            prompt = f"{prompt}\n\n---\n{reflexion_block}"
            # ToolRegistry
            tools_doc = _format_tool_schemas()
            if tools_doc:
                prompt = f"{prompt}\n\n---\n{tools_doc}"
            logger.info(f"[PERF] MODE_CONTEXTE_COMPLET | is_trivial={is_trivial}")
        else:
            logger.info(f"[PERF] MODE_CHAT_RAPIDE | skip contexte lourd | prompt_len={len(prompt)}")
        _t_prompt_done = time.time()
        _t_logging = time.time()
        log_interaction(config_name, "user", prompt[:2000])
        
        # ── Appel HTTP direct à llama-server ──
        prompt_len = len(prompt)
        _t_inference_start = time.time()
        logger.info(f"[PERF] PROMPT_SIZE | chars={prompt_len} | model={model}")
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(
                    "http://localhost:9094/v1/chat/completions",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 512,
                        "temperature": 0.3,
                    }
                )
                resp_data = resp.json()
                if "choices" in resp_data:
                    final = resp_data["choices"][0]["message"]["content"]
                    usage = resp_data.get("usage", {})
                    logger.info(f"[PERF] INFERENCE_DONE | dt={time.time()-_t_inference_start:.2f}s | prompt_tokens={usage.get('prompt_tokens','?')} | completion_tokens={usage.get('completion_tokens','?')}")
                else:
                    final = f"[ERREUR_API] {resp_data}"
                    logger.warning(f"INFERENCE_BAD_RESP | {resp_data}")
        except Exception as e:
            final = f"[ERREUR_INFERENCE] {e}"
            logger.error(f"HTTP_INFERENCE_ERROR | {e}")
        _t_inference_end = time.time()
        logger.info(f"[PERF] HTTP direct llama-server | total_dt={_t_inference_end-_t_inference_start:.2f}s")
        
        # Nettoyer les balises <thinking>
        import re
        final = re.sub(r'<thinking>.*?</thinking>', '', final, flags=re.DOTALL)
        
        _t_post_inf = time.time()
        
        # === PARSING DÉLÉGATION ===
        if model != "gemma4-12b":
            if model != "qwen3-coder-next":
                delegate_match = re.search(
                    r'<delegate_to\s+agent="qwen3-coder-next">(.*?)</delegate_to>',
                    final, flags=re.DOTALL
                )
                if delegate_match:
                    delegated_task = delegate_match.group(1).strip()
                    logger.info(f"🔀 DELEGATE | →Q3N | task_len={len(delegated_task)}")
                    _t_del_start = time.time()
                    q3n_response = await self._call_utu(delegated_task, "qwen3-coder-next", is_trivial=False)
                    logger.info(f"[PERF] DELEGATE_Q3N | dt={time.time()-_t_del_start:.2f}s")
                    final = re.sub(
                        r'<delegate_to\s+agent="qwen3-coder-next">.*?</delegate_to>',
                        f"\n[DÉLÉGUÉ À Q3N]\n{q3n_response}\n[FIN DÉLÉGATION]\n",
                        final, flags=re.DOTALL
                    )
            
            delegate_match = re.search(
                r'<delegate_to\s+agent="gemma4-12b">(.*?)</delegate_to>',
                final, flags=re.DOTALL
            )
            if delegate_match:
                delegated_task = delegate_match.group(1).strip()
                logger.info(f"🔀 DELEGATE | {model}→G4E12B | task_len={len(delegated_task)}")
                _t_del_start = time.time()
                g4_response = await self._call_utu(delegated_task, "gemma4-12b", is_trivial=False)
                logger.info(f"[PERF] DELEGATE_G4 | dt={time.time()-_t_del_start:.2f}s")
                final = re.sub(
                    r'<delegate_to\s+agent="gemma4-12b">.*?</delegate_to>',
                    f"\n[DÉLÉGUÉ À G4E12B]\n{g4_response}\n[FIN DÉLÉGATION]\n",
                    final, flags=re.DOTALL
                )
        
        _t_tool_start = time.time()
        # === PARSING APPELS D'OUTILS ===
        tool_call = parse_tool_call(final)
        if tool_call:
            tool_name = tool_call["name"]
            tool_args = tool_call["arguments"]
            logger.info(f"[PERF] TOOL_FOUND | tool={tool_name}")
            import subprocess
            try:
                if tool_name == "bash":
                    cmd = tool_args.get("command", "")
                    if cmd:
                        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=str(BASE_DIR))
                        output = result.stdout.strip() or result.stderr.strip() or "(commande exécutée, aucune sortie)"
                        if result.returncode != 0:
                            output = f"[ERREUR bash] code={result.returncode}\n{result.stderr.strip()}"
                        final = re.sub(
                            r'<execute_bash>.*?</execute_bash>',
                            f"\n[SORTIE BASH]\n{output}\n[FIN SORTIE]\n",
                            final, flags=re.DOTALL
                        )
                        final = re.sub(
                            r'<action>\s*<tool_call>\s*<tool>bash</tool>\s*<params>.*?</params>\s*</tool_call>\s*</action>',
                            f"\n[SORTIE BASH]\n{output}\n[FIN SORTIE]\n",
                            final, flags=re.DOTALL
                        )
                        final = re.sub(
                            r'''bash\(command=[\'"].*?[\'"]\)''',
                            f"\n[SORTIE BASH]\n{output}\n[FIN SORTIE]\n",
                            final
                        )
                elif tool_name == "ui_console":
                    script = tool_args.get("script", "")
                    if script:
                        try:
                            async with httpx.AsyncClient() as client:
                                resp = await client.post(
                                    "http://127.0.0.1:8095/api/ui-console/eval",
                                    json={"script": script},
                                    timeout=10.0
                                )
                                eval_data = resp.json()
                                script_id = eval_data.get("id", "")
                            if script_id:
                                result_output = None
                                for wait_i in range(30):
                                    await asyncio.sleep(1.0)
                                    async with httpx.AsyncClient() as client:
                                        sr = await client.get(
                                            f"http://127.0.0.1:8095/api/ui-console/result/{script_id}",
                                            timeout=5.0
                                        )
                                        sr_data = sr.json()
                                    if sr_data.get("status") == "completed":
                                        result_output = sr_data.get("result", "(exécuté)")
                                        break
                                    elif sr_data.get("result") is not None:
                                        result_output = sr_data["result"]
                                        break
                                output = result_output or f"(script exécuté, id={script_id})"
                            else:
                                output = f"(script mis en file, id inconnu)"
                        except Exception as e:
                            output = f"[ERREUR ui_console] {e}"
                        final = re.sub(
                            r'<execute_ui_console_script>.*?</execute_ui_console_script>',
                            f"\n[SORTIE UI CONSOLE]\n{output}\n[FIN SORTIE]\n",
                            final, flags=re.DOTALL
                        )
                else:
                    final = re.sub(
                        r'<action>\s*<tool_call>\s*<tool>' + tool_name + r'</tool>\s*<params>.*?</params>\s*</tool_call>\s*</action>',
                        f"\n[OUTIL {tool_name} : non implémenté]\n",
                        final, flags=re.DOTALL
                    )
            except subprocess.TimeoutExpired:
                final = re.sub(
                    r'<action>\s*<tool_call>\s*<tool>bash</tool>\s*<params>.*?</params>\s*</tool_call>\s*</action>',
                    f"\n[TIMEOUT bash : 30s dépassé]\n",
                    final, flags=re.DOTALL
                )
            except Exception as e:
                final = re.sub(
                    r'<action>\s*<tool_call>\s*<tool>' + tool_name + r'</tool>\s*<params>.*?</params>\s*</tool_call>\s*</action>',
                    f"\n[ERREUR {tool_name}] {e}\n",
                    final, flags=re.DOTALL
                )
        _t_tool_end = time.time()
        if tool_call:
            logger.info(f"[PERF] TOOL_EXEC | total={_t_tool_end-_t_tool_start:.2f}s")
        
        # Sliding Window + log
        _update_sliding_window(config_name, prompt[:2000], final[:2000])
        log_interaction(config_name, "assistant", final[:2000])
        
        # ── Cache Roaming (Layer 1) : sauvegarde du slot APRÈS inférence ─────
        # KV-cache = état binaire d'attention du modèle (opaque, rapide, fragile)
        # Sliding Window (Layer 2) = messages textuels de la conversation (lisible, portable)
        # Les deux sont COMPLÉMENTAIRES, pas redondants.
        # Le KV-cache préserve l'attention pattern ; le sliding window préserve le texte brut.
        try:
            await cache_manager.save_slot(slot_id=0, context_name=f"call_utu_{model}", model=gguf_model)
        except Exception:
            pass
        
        logger.info(f"[PERF] _call_utu TOTAL | dt={time.time()-_t0:.2f}s | breakdown: resolve={_t_resolve-_t0:.2f}s prompt_prep={_t_prompt_done-_t_prompt_prep:.2f}s inference={_t_inference_end-_t_inference_start:.2f}s post_inf={_t_post_inf-_t_inference_end:.2f}s tools={_t_tool_end-_t_tool_start:.2f}s")
        return final

    async def _call_utu_write(self, prompt: str, path: str, model: str = "qwen3-coder-next"):
        from pathlib import Path
        target = Path(path)
        create_backup(target)
        content = await self._call_utu(prompt, model, is_trivial=False)
        target.write_text(content, encoding="utf-8")

    def _is_safe_path(self, path: str) -> bool:
        from pathlib import Path
        try:
            resolved = Path(path).resolve()
            sandbox = BASE_DIR.resolve()
            return resolved.is_relative_to(sandbox)
        except Exception:
            return False

    def _inject_context(self, prompt: str, context: dict) -> str:
        """Injecte les résultats des étapes précédentes dans le prompt"""
        if not context:
            return prompt
        ctx_lines = [f"{k}: {v}" for k, v in context.items() if v]
        if ctx_lines:
            return f"{prompt}\n\n[CONTEXTE DES ÉTAPES PRÉCÉDENTES]\n" + "\n".join(ctx_lines)
        return prompt

    async def execute(self, task: str, context: dict = None, model_preference: str = None) -> dict:
        _t0 = time.time()
        import uuid
        context = context or {}

        # 1. Initialiser le ContractManager
        projet_id = context.get("projet_id", f"swarm-{uuid.uuid4().hex[:8]}")
        self.contract_mgr = ContractManager(projet_id=projet_id)

        try:
            contrat = self.contract_mgr.read()
        except FileNotFoundError:
            contrat = self.contract_mgr.read()
        _t_contrat = time.time()
        logger.info(f"[PERF_EXEC] contrat_read | dt={_t_contrat-_t0:.2f}s")

        # 2. Déterminer le modèle cible
        if model_preference:
            PREF_MAP = {
                "qwen3.6": "qwen3.6-35b", "qwen3.6-35b": "qwen3.6-35b",
                "qwen3-coder": "qwen3-coder-next",
                "qwen3-coder-80b": "qwen3-coder-next-80b-gguf",
                "gemma4-12b": "gemma4-12b",
            }
            target_model = PREF_MAP.get(model_preference, "qwen3.6-35b")
            target_actor = self._resolve_model_to_actor(target_model)
        elif contrat.workflow.next_actor_requested:
            target_actor = contrat.workflow.next_actor_requested
            target_model = self._resolve_actor_to_model(target_actor)
        else:
            target_actor = contrat.workflow.current_actor
            target_model = self._resolve_actor_to_model(target_actor)
        _t_route = time.time()
        logger.info(f"[PERF_EXEC] routing | dt={_t_route-_t_contrat:.2f}s | target={target_model}")

        self.logs.append({"step": 1, "action": "contrat_read", "model": target_model, "actor": target_actor})
        self.contract_mgr.add_history_entry(actor=target_actor, action=f"Début : {task[:100]}")

        # 5. Construire le prompt — contrat injecté UNIQUEMENT pour tâches non-triviales
        is_trivial = (len(task.strip()) < 80 and not any(k in task.lower() for k in 
            ["code", "fichier", "file", "bash", "shell", "créer", "modifie", "lit", "écrit", 
             "analyse", "review", "valide", "test", "fix", "implémente", "déploie",
             "vision", "screenshot", "ui", "interface", "délègue", "commande"]))
        if is_trivial:
            contrat_block = ""
            logger.info(f"[PERF_EXEC] TACHE_TRIVIALE | skip contrat | task_len={len(task)}")
        else:
            contrat_block = self._format_contrat_block(contrat)
        full_prompt = f"{contrat_block}\n\nTÂCHE : {task}" if contrat_block else task
        _t_prompt = time.time()
        logger.info(f"[PERF_EXEC] prompt_prep | dt={_t_prompt-_t_route:.2f}s")

        # 6. Inférence
        try:
            _t_inf_start = time.time()
            final_result = await self._call_utu(full_prompt, target_model, is_trivial=is_trivial)
            _t_inf_end = time.time()
            logger.info(f"[PERF_EXEC] _call_utu | dt={_t_inf_end-_t_inf_start:.2f}s")
        except Exception as e:
            logger.error(f"SWARM_FALLBACK_ERROR | model={target_model} | error={e}")
            final_result = f"⚠️ Erreur {target_model} : {e}."
            self.contract_mgr.update_and_save({"status": "FAILED", "workflow": {"next_actor_requested": "Q3.6", "reason": str(e)[:200]}})
            self.step_results["result"] = final_result
            self.logs.append({"step": 2, "action": "response", "model": target_model, "error": str(e)})
            return {"success": False, "model_used": target_model, "response": final_result, "steps": self.logs, "step_results": dict(self.step_results), "status": "failed"}

        # 7. Parser contrat
        _t_parse_start = time.time()
        parsed = self._parse_contrat_tag(final_result)
        flush_sliding_window_to_logs(projet_id=projet_id)

        if parsed:
            next_actor = parsed.get("next_actor", "Q3.6")
            validation = parsed.get("validation", "false").lower() == "true"
            update_dict = {"workflow": {"current_actor": target_actor, "next_actor_requested": next_actor}}
            if validation and target_actor not in contrat.validations_actuelles:
                update_dict.setdefault("validations_actuelles", {})[target_actor] = True
            all_v = all(contrat.validations_actuelles.get(a, False) or (a == target_actor and validation) for a in contrat.consensus_requis)
            update_dict["status"] = "DONE" if all_v or next_actor == "DONE" else "REVIEW" if next_actor in ("Q3.6", "G4E12B") else "CODING"
            self.contract_mgr.update_and_save(update_dict)
        else:
            self.contract_mgr.update_and_save({"status": "FAILED"})
        _t_parse_end = time.time()
        logger.info(f"[PERF_EXEC] contrat_parse+flush | dt={_t_parse_end-_t_parse_start:.2f}s")

        # 8. Nettoyer
        import re
        clean_response = re.sub(r'<contrat\s+[^>]+/?>', '', final_result).strip()
        self.step_results["result"] = clean_response
        self.logs.append({"step": 2, "action": "response", "model": target_model})

        _t_total = time.time() - _t0
        logger.info(f"[PERF_EXEC] execute TOTAL | dt={_t_total:.2f}s | breakdown: contrat={_t_contrat-_t0:.2f}s routing={_t_route-_t_contrat:.2f}s prompt={_t_prompt-_t_route:.2f}s call_utu={_t_inf_end-_t_inf_start:.2f}s parse={_t_parse_end-_t_parse_start:.2f}s")

        return {"success": True, "model_used": target_model, "response": clean_response, "steps": self.logs, "step_results": dict(self.step_results), "status": "completed"}

@app.post("/agent/swarm/queue")
async def queue_swarm_task(req: dict):
    task = req.get("task", "")
    path = req.get("path", "UI_FIX_LOG.md")
    mode = req.get("mode", "utu-realiamdev")
    if not task:
        return {"success": False, "error": "task requis"}
    
    task_id = str(uuid4())
    payload = {"task": task, "context": {"path": path}, "mode": mode}
    SWARM_TASKS[task_id] = {"status": "queued", "task": task, "created_at": True}
    await SWARM_QUEUE.put((task_id, payload))
    logger.info(f"SWARM_QUEUED | task_id={task_id} | task_len={len(task)}")
    return {"success": True, "task_id": task_id, "status": "queued", "message": "Tâche ajoutée à la file"}

@app.get("/swarm/status/{task_id}")
async def get_swarm_status(task_id: str):
    if task_id not in SWARM_TASKS:
        return format_ui_payload(
            agent_name="orchestrateur",
            status="error",
            message=f"Tâche {task_id} introuvable",
            metrics={"task_id": task_id}
        )
    
    task_data = SWARM_TASKS[task_id]
    task_status = task_data["status"]
    model_used = task_data.get("result", {}).get("model_used", "gemma4-e4b")
    steps = task_data.get("result", {}).get("steps", [])
    
    msg = f"Swarm {task_id} → {task_status}"
    if task_status == "completed":
        msg = f"Swarm {task_id} terminé ({len(steps)} étapes, modèle: {model_used})"
    elif task_status == "failed":
        msg = f"Swarm {task_id} échoué: {task_data.get('error', 'erreur inconnue')}"
    
    return format_ui_payload(
        agent_name=model_used,
        status=task_status,
        message=msg,
        metrics={
            "task_id": task_id,
            "model_used": model_used,
            "steps": len(steps),
            "step_results": task_data.get("result", {}).get("step_results", {}),
            "error": task_data.get("error"),
            "created_at": task_data.get("created_at")
        }
    )

@app.get("/api/task/{task_id}/status")
async def api_task_status_alias(task_id: str):
    """
    Endpoint polling frontend.
    Retourne les clés exactes attendues par sendMessage() :
      - status : 'queued' | 'running' | 'completed' | 'failed'
      - step_results : dict avec .result, .text, .vision, etc.
      - response / message / model_used / error
    """
    if task_id not in SWARM_TASKS:
        return {"status": "unknown", "error": f"Tâche {task_id} introuvable"}
    
    td = SWARM_TASKS[task_id]
    result_data = td.get("result", {}) or {}
    step_results = result_data.get("step_results", {}) or {}
    task_status = td.get("status", "unknown")
    model_used = result_data.get("model_used", "qwen3.6-35b")
    response_text = step_results.get("result", "") or result_data.get("response", "")
    error_text = td.get("error", "") or result_data.get("error", "")
    
    return {
        "status": task_status,
        "step_results": step_results,
        "response": response_text,
        "message": result_data.get("message", ""),
        "model_used": model_used,
        "error": error_text
    }
# =====================================

# ── Proxy endpoints vers Station (port 8090) ────────────────────────────
STATION_URL = "http://localhost:8090"

@app.get("/status")
async def proxy_status():
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{STATION_URL}/status", timeout=5.0)
            return format_ui_payload(
                agent_name="station",
                status="idle",
                message="Station Realia accessible",
                metrics={"station_response": r.json()}
            )
    except Exception as exc:
        return format_ui_payload(
            agent_name="station",
            status="error",
            message="Station Realia indisponible",
            metrics={"detail": str(exc)}
        )

@app.get("/api/files")
async def proxy_files(path: str = "/"):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{STATION_URL}/api/files", params={"path": path}, timeout=10.0)
            return r.json()
    except Exception as exc:
        return {"error": "Station unavailable", "detail": str(exc)}

@app.get("/api/youtu/status")
async def proxy_youtu():
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{STATION_URL}/api/youtu/status", timeout=5.0)
            return r.json()
    except Exception as exc:
        return {"error": "Station unavailable", "detail": str(exc)}

# ── UI Console Endpoints (Gemma4 execute_ui_console_script) ────────────
import uuid as _uuid

@app.post("/api/ui-console/eval")
async def ui_console_eval(req: dict):
    """
    Reçoit un script JS à exécuter dans l'UI web.
    Le script est mis dans une file ; l'UI le récupère via /api/ui-console/next.
    """
    script = req.get("script", "")
    if not script or not isinstance(script, str):
        return {"success": False, "error": "script requis (string)"}
    if len(script) > 100000:
        return {"success": False, "error": "script > 100KB"}
    
    script_id = _uuid.uuid4().hex[:16]
    entry = {"id": script_id, "script": script, "created_at": time.time()}
    await UI_CONSOLE_SCRIPTS.put(entry)
    logger.info(f"UI_CONSOLE_EVAL | id={script_id} | len={len(script)}")
    return {"success": True, "id": script_id, "status": "queued"}


@app.get("/api/ui-console/next")
async def ui_console_next():
    """
    L'UI interroge cet endpoint périodiquement.
    Retourne le prochain script à exécuter, ou null si file vide.
    """
    try:
        # get_nowait() est non-bloquant : si la file est vide, on répond IMMÉDIATEMENT
        # (évite de bloquer le navigateur 15s et les timeouts navigateur)
        entry = UI_CONSOLE_SCRIPTS.get_nowait()
        return {
            "script": entry["script"],
            "id": entry["id"],
            "created_at": entry["created_at"]
        }
    except asyncio.QueueEmpty:
        return {"script": None, "id": None}


@app.post("/api/ui-console/result")
async def ui_console_result(req: dict):
    """
    L'UI renvoie le résultat d'exécution d'un script.
    """
    script_id = req.get("id", "")
    result = req.get("result", "")
    error = req.get("error", "")
    if script_id:
        UI_CONSOLE_RESULTS[script_id] = result or error or "(exécuté)"
        logger.info(f"UI_CONSOLE_RESULT | id={script_id} | len={len(result or error)}")
    return {"success": True}


@app.get("/config/feature-flags")
async def get_feature_flags_endpoint():
    """Retourne feature flags pour frontend (API Contract v1.0.0)."""
    return get_feature_flags()


@app.get("/api/ui-console/result/{script_id}")
async def ui_console_get_result(script_id: str):
    """
    Gemma4 interroge cet endpoint pour récupérer le résultat d'un script.
    """
    result = UI_CONSOLE_RESULTS.get(script_id)
    if result is None:
        return {"success": True, "result": None, "status": "pending"}
    return {"success": True, "result": result, "status": "completed"}
# ===========================================

# ── Auto-RAG Module (RAGChunk + Index + Status) ──────────────────────────
class RAGChunk(BaseModel):
    type: str
    content: str
    timestamp: str | None = None
    session: str | None = None

rag_router = APIRouter(prefix="/api/rag", tags=["RAG"])

@rag_router.post("/index")
async def rag_index(chunk: RAGChunk):
    """Index a RAG chunk into rag/index.jsonl"""
    try:
        import os
        from datetime import datetime, timezone
        rag_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rag")
        os.makedirs(rag_dir, exist_ok=True)
        index_path = os.path.join(rag_dir, "index.jsonl")
        record = chunk.model_dump()
        if record["timestamp"] is None:
            record["timestamp"] = datetime.now(timezone.utc).isoformat()
        if record["session"] is None:
            record["session"] = "vision_fix"
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"status": "indexed", "path": "rag/index.jsonl"}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))

@rag_router.get("/status")
async def rag_status():
    """Check status of rag/index.jsonl"""
    import os
    rag_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rag")
    index_path = os.path.join(rag_dir, "index.jsonl")
    if not os.path.exists(index_path):
        return {"exists": False, "path": "rag/index.jsonl", "lines": 0}
    with open(index_path, "r", encoding="utf-8") as f:
        lines = sum(1 for _ in f)
    return {"exists": True, "path": "rag/index.jsonl", "lines": lines}

app.include_router(rag_router)
# =======================================================

# ── Main ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("🧰 DevKit Orchestrator (UTU Core) → http://0.0.0.0:8095/docs")
    uvicorn.run(app, host="0.0.0.0", port=8095)
