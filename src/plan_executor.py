"""
plan_executor.py
Boucle Python d'exécution de plan pilotée par Gemma4.
Parse le JSON du plan, appelle SimpleAgent.run(), gère le KV Cache,
boucle de validation, et retourne le résultat final.

DevSenior: Python = exécuteur d'infra uniquement.
Toute décision métier (modèle, validation, correction) est prise par Gemma4.
"""

import json
import time
import re
import asyncio
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

from plan_executor_exceptions import PlanExecutorError, PlanExecutionInProgress, CircularDependencyError, AgentCreationError, InvalidStepError, ModelSwapError, LLMTimeoutError, DuplicateStepError, EmptyPlanError
from realia_devkit.ws_broadcaster import broadcaster
from realia_devkit.feature_flags import flags

from planner_template import get_planner_prompt
from validator_template import get_validator_prompt
from cache_roaming import CacheRoaming

# DevSenior: CACHE_ENGINE est défini dans devkit_orchestrator.py, pas ici.
# Le PlanExecutor reçoit une instance optionnelle via le constructeur.
from build_hierarchical_prompt import N1_SYSTEM, hash_prefix

logger = logging.getLogger("devkit.plan_executor")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[PLAN_EXEC] %(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)


# ─── Constantes ──────────────────────────────────────────────────────────
RAG_LONG_TERME_FILE = Path(__file__).parent / "rag_long_terme.txt"
RAG_LONG_TERME = RAG_LONG_TERME_FILE.read_text(encoding="utf-8") if RAG_LONG_TERME_FILE.exists() else ""
MAX_LOOP_ITERATIONS = 3  # Nombre max de tentatives de correction par étape


# === CONSTANTES DE CONFIGURATION ===
# Modèles
PLANNER_MODEL = "gemma4-12b"          # Modèle par défaut pour le planning
EXECUTOR_MODEL = "qwen3-coder-next"   # Modèle par défaut pour l'exécution
FALLBACK_MODEL_1 = "qwen3.6-35b"      # Premier fallback
FALLBACK_MODEL_2 = "gemma4-12b"       # Second fallback
# Timeouts
LLM_TIMEOUT_SECONDS = 60              # Timeout pour appels LLM (secondes)
# Troncatures
FEEDBACK_TRUNC_LENGTH = 200           # Longueur max feedback validation
SUGGESTED_FIX_TRUNC_LENGTH = 500      # Longueur max suggested_fix
FILE_CONTENT_LIMIT = 3000             # Taille max contenu fichier lu
OUTPUT_TRUNC_LENGTH = 300             # Longueur max output exécution


def normalize_plan_output(raw: str) -> str:
    """Extrait le JSON d'un plan depuis la réponse Gemma4.
    Gère les cas avec ```json, ```, ou texte autour.
    """
    if not raw:
        return "[]"
    
    # Essayer d'extraire un bloc JSON entre ```json ... ```
    json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', raw, re.DOTALL)
    if json_match:
        return json_match.group(1).strip()
    
    # Essayer de trouver un tableau JSON directement
    array_match = re.search(r'(\[.*?\])', raw, re.DOTALL)
    if array_match:
        candidate = array_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass
    
    return raw.strip()


def normalize_json_output(raw: str) -> str:
    """Extrait un objet JSON depuis une réponse.
    Gère les cas avec ```json, ```, ou texte autour.
    """
    if not raw:
        return "{}"
    
    # Essayer d'extraire un bloc JSON entre ```json ... ```
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
    if json_match:
        return json_match.group(1).strip()
    
    # Essayer de trouver un objet JSON directement
    obj_match = re.search(r'(\{.*?\})', raw, re.DOTALL)
    if obj_match:
        candidate = obj_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass
    
    return raw.strip()


class PlanExecutor:
    """Exécute un plan généré par Gemma4.
    
    Cycle : PLAN → EXECUTE → VALIDATE → LOOP/TERMINATE
    - PLAN : Gemma4 génère un plan JSON
    - EXECUTE : Python lit le plan, appelle chaque modèle via SimpleAgent
    - VALIDATE : Gemma4 valide chaque étape
    - LOOP : Si fail, on corrige et on réessaie
    - TERMINATE : Retour final au frontend
    """
    
    def __init__(self, cache_engine: Optional[CacheRoaming] = None):
        self.cache = cache_engine  # DevSenior: instance optionnelle
        self.step_results: Dict[int, Dict[str, Any]] = {}
        self.plan: List[Dict[str, Any]] = []
        self.loop_count: int = 0
        self.max_loops: int = MAX_LOOP_ITERATIONS
        self._execution_lock = asyncio.Lock()  # EC-28 : verrou d'exécution concurrente
    
    def _detect_circular_dependencies(self, plan) -> None:
        """Détecte les dépendances circulaires dans le plan (EC-03).
        
        Algorithme DFS avec détection de back-edge.
        Si un cycle est détecté, lève CircularDependencyError.
        
        Args:
            plan: Liste des étapes du plan
            
        Raises:
            CircularDependencyError: Si une dépendance circulaire est détectée
        """
        # Construire le graphe des dépendances
        graph = {}
        for step in plan:
            step_num = step.get("step")
            depends_on = step.get("depends_on", [])
            if depends_on is None:
                depends_on = []
            graph[step_num] = depends_on
        
        # DFS avec détection de cycle
        visited = set()
        rec_stack = set()
        
        def dfs(node):
            visited.add(node)
            rec_stack.add(node)
            for dep in graph.get(node, []):
                if dep not in visited:
                    if dfs(dep):
                        return True
                elif dep in rec_stack:
                    raise CircularDependencyError(node, dep)
            rec_stack.remove(node)
            return False
        
        for step_num in graph:
            if step_num not in visited:
                dfs(step_num)

    def _detect_duplicate_steps(self, plan) -> None:
        """Détecte les steps dupliqués dans le plan (EC-17)."""
        seen_steps = set()
        for step in plan:
            step_num = step.get("step")
            if step_num in seen_steps:
                raise DuplicateStepError(step_num)
            seen_steps.add(step_num)

    # ─── ÉTAPE 1 : PLAN ─────────────────────────────────────────────────
    async def generate_plan(self, task: str, context: dict = None, agent=None) -> List[Dict[str, Any]]:
        """Appelle Gemma4 pour générer un plan JSON.
        
        Args:
            task: La demande utilisateur
            context: Contexte optionnel (path, historique)
            agent: Instance SimpleAgent pré-construite (ou None pour en créer une)
        
        Returns:
            Liste des étapes du plan
        """
        from utu.agents import SimpleAgent
        
        prompt = get_planner_prompt(task, context)
        
        # Cache le préfixe N1+N2 pour accélérer les appels suivants
        prefix_hash = hash_prefix(N1_SYSTEM, RAG_LONG_TERME)
        
        if self.cache:
            try:
                self.cache.restore(prefix_hash, PLANNER_MODEL)
            except Exception as e:
                logger.warning(f"Cache restore failed (continuing without cache): {e}")
        
        should_close = False
        if agent is None:
            agent = SimpleAgent(config="realia_dev")
            await agent.__aenter__()
            should_close = True
        
        try:
            result = await agent.run(prompt)
            raw_plan = str(result.final_output)
        finally:
            if should_close:
                await agent.__aexit__(None, None, None)
        
        # Snapshot N1+N2 après génération du plan
        if self.cache:
            try:
                self.cache.snapshot(prefix_hash, PLANNER_MODEL)
            except Exception as e:
                logger.warning(f"Cache snapshot failed (plan generated but not cached): {e}")
        
        # Nettoyage et parsing du JSON
        json_str = normalize_plan_output(raw_plan)
        try:
            plan = json.loads(json_str)
            if not isinstance(plan, list):
                logger.warning(f"PLAN_PARSE_WARN | attendu liste, reçu {type(plan)}")
                plan = [{"step": 1, "model": PLANNER_MODEL, "action": "chat",
                         "instruction": task, "success_criteria": "réponse produite", "depends_on": None}]
        except json.JSONDecodeError as e:
            logger.error(f"PLAN_PARSE_FAIL | {e} | raw={raw_plan[:FEEDBACK_TRUNC_LENGTH]}")
            # Fallback : plan minimal
            plan = [{"step": 1, "model": PLANNER_MODEL, "action": "chat",
                     "instruction": task, "success_criteria": "réponse produite", "depends_on": None}]
        
        self.plan = plan
        logger.info(f"SWARM_PLAN_GENERATED | steps={len(plan)} | task_len={len(task)}")
        for step in plan:
            logger.info(f"SWARM_PLAN_STEP | step={step.get('step')} | model={step.get('model')} | action={step.get('action')}")
        
        return plan
    
    # ─── ÉTAPE 2 : EXECUTE ──────────────────────────────────────────────
    async def execute_step(self, step: Dict[str, Any], context: dict = None, agent=None) -> str:
        """Exécute une étape du plan avec le modèle spécifié.
        
        Args:
            step: Dictionnaire de l'étape (step, model, action, instruction, success_criteria)
            context: Contexte global (path de fichier, etc.)
            agent: Instance SimpleAgent pré-construite
        
        Returns:
            Output brut de l'étape
        """
        from utu.agents import SimpleAgent
        
        step_num = step.get("step", 1)
        model = step.get("model", FALLBACK_MODEL_1)
        action = step.get("action", "chat")
        instruction = step.get("instruction", "")
        if not instruction:
            raise InvalidStepError(step_num, "Instruction manquante ou vide")
        file_path = context.get("path") if context else None
        
        # EC-13 : si action=code, file_path est obligatoire
        if action == "code" and not file_path:
            raise InvalidStepError(step_num, "file_path manquant pour l'action 'code'")
        
        # Mapping modèle → config UTU
        config_map = {
            FALLBACK_MODEL_1: "realia_qwen36",
            EXECUTOR_MODEL: "realia_coder",
            PLANNER_MODEL: "realia_g4_12b",
        }
        if model not in config_map:
            logger.warning(
                f"Model '{model}' not in config_map, falling back to 'realia_dev'. "
                f"Available models: {list(config_map.keys())}"
            )
        config_name = config_map.get(model, "realia_dev")
        
        # Construire le prompt avec contexte des étapes précédentes
        prompt_parts = [instruction]
        if self.step_results:
            ctx_lines = []
            for s_num, s_result in self.step_results.items():
                output = str(s_result.get("output", ""))
                # EC-30 : marker troncature visible
                if len(output) > OUTPUT_TRUNC_LENGTH:
                    logger.info(
                        f"EC-30: Step {s_num} output truncated from {len(output)} to {OUTPUT_TRUNC_LENGTH} chars"
                    )
                    preview = output[:OUTPUT_TRUNC_LENGTH] + "\n[...TRUNCATED...]"
                else:
                    preview = output
                ctx_lines.append(f"--- Résultat Étape {s_num} ---\n{preview}")
            if ctx_lines:
                prompt_parts.append("\n\n[CONTEXTE DES ÉTAPES PRÉCÉDENTES]\n" + "\n\n".join(ctx_lines))
        
        # Ajouter le contexte de fichier si présent
        if file_path and action == "code":
            prompt_parts.append(f"\n\n[FICHIER CIBLE]\n{file_path}")
            # Ajouter le contenu actuel du fichier s'il existe
            try:
                p = Path(file_path)
                if p.exists():
                    content = p.read_text(encoding="utf-8")
                    prompt_parts.append(f"\n[CONTENU ACTUEL]\n{content[:FILE_CONTENT_LIMIT]}")
                    if len(content) > FILE_CONTENT_LIMIT:
                        prompt_parts.append("\n[...]")
            except Exception:
                pass
        
        # Pour action "code", demander UNIQUEMENT le contenu modifié
        if action == "code":
            prompt_parts.append("\n\nRÉPONDS UNIQUEMENT avec le contenu COMPLET du fichier après modification. Pas d'explications, pas de markdown.")
        
        full_prompt = "\n".join(prompt_parts)
        
        # DevSenior: swap VRAM séquentiel avant chaque inférence
        from devkit_orchestrator import swapper  # instance globale ModelSwapper
        if not swapper.swap(model):
            logger.warning(f"SWARM_SWAP_FALLBACK | step={step_num} | model={model}")
            # EC-24 : essayer des fallbacks pour le code
            if action == "code":
                fallback_models = [FALLBACK_MODEL_1, PLANNER_MODEL]
                swapped = False
                for fallback in fallback_models:
                    if fallback != model and swapper.swap(fallback):
                        logger.warning(f"Model '{model}' unavailable, using fallback '{fallback}' for step {step_num}")
                        model = fallback
                        swapped = True
                        break
                if not swapped:
                    raise ModelSwapError(f"Tous les fallbacks echoues pour {model}", step_num)
            else:
                raise ModelSwapError(model, step_num)  # EC-04 : swap échoué
        
        # Cache le préfixe N1+N2
        prefix_hash = hash_prefix(N1_SYSTEM, RAG_LONG_TERME)
        if self.cache:
            self.cache.restore(prefix_hash, model)
        
        should_close = False
        if agent is None:
            try:
                agent = SimpleAgent(config=config_name)
                await agent.__aenter__()
            except Exception as e:
                logger.error(f"AGENT_CREATE_FAIL | step={step_num} | model={model} | config={config_name} | error={e}")
                raise AgentCreationError(model, str(e)) from e
            should_close = True
        
        try:
            result = await asyncio.wait_for(
                agent.run(full_prompt),
                timeout=LLM_TIMEOUT_SECONDS  # EC-07 : timeout LLM
            )
            output = str(result.final_output) if result.final_output else ""
        except asyncio.TimeoutError:
            raise LLMTimeoutError(model, LLM_TIMEOUT_SECONDS)
        finally:
            if should_close:
                await agent.__aexit__(None, None, None)
        
        # Snapshot N1+N2 après exécution
        if self.cache:
            self.cache.snapshot(prefix_hash, model)
        
        # Si action=code et file_path, écrire le résultat dans le fichier
        if action == "code" and file_path:
            try:
                from sandbox import sandbox_write
                sandbox_write(Path(file_path), output)
                logger.info(f"PLAN_EXEC_WRITE | step={step_num} | path={file_path} | size={len(output)}")
            except Exception as e:
                logger.error(f"PLAN_EXEC_WRITE_FAIL | step={step_num} | error={e}")
        
        # Stocker le résultat
        self.step_results[step_num] = {
            "output": output,
            "model": model,
            "action": action,
            "file_path": file_path,
        }
        
        logger.info(f"SWARM_STEP_EXECUTE | step={step_num} | model={model} | action={action} | output_len={len(output)}")
        return output
    
    # ─── ÉTAPE 3 : VALIDATE ─────────────────────────────────────────────
    async def validate_step(self, step: Dict[str, Any], step_output: str, agent=None) -> Dict[str, str]:
        """Valide le résultat d'une étape via Gemma4.
        
        Args:
            step: Dictionnaire de l'étape
            step_output: Output de l'étape à valider
            agent: Instance SimpleAgent pré-construite
        
        Returns:
            Dictionnaire {"status": "pass"|"fail"|"next", "feedback": "...", "suggested_fix": "..."}
        """
        from utu.agents import SimpleAgent
        
        step_num = step.get("step", 1)
        instruction = step.get("instruction", "")
        success_criteria = step.get("success_criteria", "")
        file_path = self.step_results.get(step_num, {}).get("file_path")
        
        prompt = get_validator_prompt(instruction, success_criteria, step_output, file_path)
        
        should_close = False
        if agent is None:
            agent = SimpleAgent(config="realia_dev")
            await agent.__aenter__()
            should_close = True
        
        try:
            result = await asyncio.wait_for(
                agent.run(prompt),
                timeout=LLM_TIMEOUT_SECONDS  # EC-07 : timeout LLM
            )
            raw_validation = str(result.final_output)
        except asyncio.TimeoutError:
            raise LLMTimeoutError(PLANNER_MODEL, LLM_TIMEOUT_SECONDS)
        finally:
            if should_close:
                await agent.__aexit__(None, None, None)
        
        # Parser le JSON de validation
        json_str = normalize_json_output(raw_validation)
        try:
            validation = json.loads(json_str)
            if not isinstance(validation, dict):
                validation = {"status": "pass", "feedback": raw_validation[:FEEDBACK_TRUNC_LENGTH]}
        except json.JSONDecodeError:
            # Fallback : si on ne peut pas parser, on cherche "pass"/"fail"/"next" dans le texte
            lower = raw_validation.lower()
            if "pass" in lower or "ok" in lower or "succès" in lower or "valid" in lower:
                validation = {"status": "pass", "feedback": raw_validation[:FEEDBACK_TRUNC_LENGTH]}
            elif "fail" in lower or "erreur" in lower or "corrig" in lower:
                validation = {"status": "fail", "feedback": raw_validation[:FEEDBACK_TRUNC_LENGTH], "suggested_fix": raw_validation[:SUGGESTED_FIX_TRUNC_LENGTH]}
            else:
                validation = {"status": "pass", "feedback": "Validation implicite : décision non trouvée dans la réponse"}
        
        # Log structuré
        status = validation.get("status", "pass")
        if status == "pass":
            logger.info(f"SWARM_VALIDATE_PASS | step={step_num} | feedback={validation.get('feedback', '')[:100]}")
        elif status == "fail":
            logger.warning(f"SWARM_VALIDATE_FAIL | step={step_num} | feedback={validation.get('feedback', '')[:100]}")
        elif status == "next":
            logger.info(f"SWARM_VALIDATE_NEXT | step={step_num} | feedback={validation.get('feedback', '')[:100]}")
        
        return validation
    
    # ─── BOUCLE PRINCIPALE ──────────────────────────────────────────────
    async def execute_plan(self, task: str, context: dict = None) -> Dict[str, Any]:
        """Boucle complète PLAN -> EXECUTE -> VALIDATE -> LOOP/TERMINATE.

        Protégé par verrou d'exécution concurrente (EC-28).
        """
        context = context or {}

        # EC-28 : verrou d'exécution concurrente
        if not self._execution_lock.locked():
            await self._execution_lock.acquire()
        else:
            raise PlanExecutionInProgress("execute_plan() déjà en cours")

        try:
            return await self._execute_plan_impl(task, context)
        finally:
            self._execution_lock.release()

    async def _execute_plan_impl(self, task: str, context: dict = None, task_id: str = None) -> Dict[str, Any]:
        """Boucle complète PLAN → EXECUTE → VALIDATE → LOOP/TERMINATE.
        
        Args:
            task: La demande utilisateur
            context: Contexte (path, etc.)
        
        Returns:
            Résultat final structuré
        """
        from utu.agents import SimpleAgent
        
        context = context or {}
        self.step_results = {}
        self.loop_count = 0
        self.plan = []
        file_path = context.get("path")
        
        start_time = time.time()
        
        # ─── Agent global pour réutiliser le cache contexte ───
        async with SimpleAgent(config="realia_dev") as g4_agent:
            
            # ════════════ PHASE 1 : PLAN ════════════
            logger.info("SWARM_PLAN_START | generation du plan par Gemma4")
            plan = await self.generate_plan(task, context, agent=g4_agent)
            self._detect_circular_dependencies(plan)  # EC-03 : detection de cycle
            self._detect_duplicate_steps(plan)  # EC-17 : detection doublons
            
            # EC-01 : plan vide → fallback minimal
            if not plan:
                logger.warning(f"Empty plan generated, using fallback minimal plan")
                plan = [{
                    "step": 1,
                    "action": "chat",
                    "model": PLANNER_MODEL,
                    "instruction": f"Expliquer pourquoi la tâche '{task}' n'a pas pu être planifiée.",
                    "success_criteria": "Réponse informative produite",
                    "depends_on": None
                }]
            
            # ════════════ PHASE 2-3-4 : EXECUTE + VALIDATE + LOOP ════════════
            all_passed = True
            for step in plan:
                step_num = step.get("step", 1)
                model = step.get("model", FALLBACK_MODEL_1)
                action = step.get("action", "chat")
                instruction = step.get("instruction", "")
                depends_on = step.get("depends_on")
                
                # Vérifier les dépendances
                if depends_on:
                    missing = [d for d in depends_on if d not in self.step_results]
                    if missing:
                        logger.warning(f"SWARM_DEP_MISSING | step={step_num} | missing_deps={missing}")
                        # Continuer quand même avec ce qu'on a
                
                # ─── Boucle de correction ───
                step_passed = False
                attempt = 0
                current_output = ""
                validation = {"status": "fail", "feedback": "Défaut"}
                
                while not step_passed and attempt <= self.max_loops:
                    if attempt > 0:
                        logger.info(f"SWARM_LOOP | step={step_num} | attempt={attempt}/{self.max_loops}")
                        self.loop_count += 1
                        if flags.USE_WEBSOCKET and task_id:
                            await broadcaster.emit_task_progress(task_id, step_num, len(self.plan) or 1, instruction[:50])  # compter cette iteration comme une retry
                        # Ajouter le feedback de validation comme contexte de correction
                        fix_instruction = instruction
                        if validation.get("suggested_fix"):
                            fix_instruction += f"\n\n[FEEDBACK CORRECTION]\n{validation['suggested_fix']}"
                        corrected_step = {**step, "instruction": fix_instruction}
                        try:
                            current_output = await self.execute_step(corrected_step, context)
                        except PlanExecutorError as e:
                            logger.error(f"EXEC_STEP_FAIL | step={step_num} | attempt={attempt} | error={e}")
                            validation = {"status": "fail", "feedback": str(e)[:FEEDBACK_TRUNC_LENGTH],
                                          "suggested_fix": f"Erreur lors de l'exécution : {e}"}
                            step_passed = False
                            attempt += 1
                            continue
                    else:
                        try:
                            current_output = await self.execute_step(step, context)
                        except PlanExecutorError as e:
                            logger.error(f"EXEC_STEP_FAIL | step={step_num} | attempt=0 | error={e}")
                            validation = {"status": "fail", "feedback": str(e)[:FEEDBACK_TRUNC_LENGTH],
                                          "suggested_fix": f"Erreur lors de l'exécution : {e}"}
                            step_passed = False
                            attempt += 1
                            continue
                    
                    # VALIDATE (sauf pour action=chat triviale)
                    if action == "chat" and len(current_output) > 0:
                        step_passed = True
                        validation = {"status": "pass", "feedback": "Réponse produite"}
                        logger.info(f"SWARM_VALIDATE_PASS | step={step_num} | action=chat implicite")
                    else:
                        validation = await self.validate_step(step, current_output, agent=g4_agent)
                        step_passed = validation.get("status") == "pass"
                        
                        # Si "next", on exécute une étape supplémentaire
                        if validation.get("status") == "next":
                            logger.info(f"SWARM_NEXT_STEP | step={step_num} | etape supplementaire requise")
                            # Créer une étape supplémentaire avec l'instruction de next_step
                            next_instr = validation.get("next_step_instruction", "")
                            if next_instr:
                                next_step = {
                                    "step": step_num + 0.5,  # Étape intermédiaire
                                    "model": model,
                                    "action": action,
                                    "instruction": next_instr,
                                    "success_criteria": step.get("success_criteria", ""),
                                    "depends_on": [step_num]
                                }
                                current_output = await self.execute_step(next_step, context)
                                # Re-valider
                                validation = await self.validate_step(step, current_output, agent=g4_agent)
                                step_passed = validation.get("status") == "pass"
                            else:
                                step_passed = True  # Next sans instruction = on passe
                    
                    attempt += 1
                
                # Mise à jour du résultat final de l'étape
                self.step_results[step_num] = {
                    **self.step_results.get(step_num, {}),
                    "output": current_output,
                    "validation": validation,
                    "passed": step_passed,
                    "attempts": attempt,
                }
                
                if not step_passed:
                    all_passed = False
                    logger.warning(f"SWARM_STEP_FAILED | step={step_num} | apres {attempt} tentatives")
            
            # ════════════ PHASE FINALE : RAPPORT ════════════
            elapsed = time.time() - start_time
            logger.info(f"SWARM_COMPLETE | steps_executed={len(plan)} | loops={self.loop_count} | time={elapsed:.1f}s")
            
            # Construire le rapport final
            final_output_parts = []
            for step in plan:
                step_num = step.get("step", 1)
                result = self.step_results.get(step_num, {})
                val = result.get("validation", {})
                status_icon = "✅" if result.get("passed") else "❌"
                final_output_parts.append(
                    f"{status_icon} Étape {step_num} ({step.get('model')} - {step.get('action')}): "
                    f"{val.get('feedback', 'exécuté')[:FEEDBACK_TRUNC_LENGTH]}"
                )
            
            final_summary = "\n".join(final_output_parts)
            
            # Si tout est passé mais qu'il faut un résumé Gemma4
            if all_passed and len(plan) > 1:
                summary_prompt = (
                    f"Résume en français ce qui a été fait dans ce plan d'exécution :\n"
                    f"Tâche originale : {task}\n\n"
                    f"{final_summary}\n\n"
                    f"Donne un résumé clair et professionnel de ce qui a été accompli."
                )
                summary_result = await g4_agent.run(summary_prompt)
                final_summary = str(summary_result.final_output)
            
            return {
                "success": all_passed,
                "final_output": final_summary,
                "plan": plan,
                "step_results": {
                    str(k): {
                        "output": v.get("output", ""),
                        "model": v.get("model", ""),
                        "action": v.get("action", ""),
                        "validation": v.get("validation", {}),
                        "passed": v.get("passed", False),
                        "attempts": v.get("attempts", 0),
                    }
                    for k, v in self.step_results.items()
                },
                "loops": self.loop_count,
                "time_elapsed_s": round(elapsed, 1),
                "status": "completed" if all_passed else "completed_with_errors",
            }
