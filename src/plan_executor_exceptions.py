"""
plan_executor_exceptions.py
Exceptions spécifiques du PlanExecutor.
Utilisées par le contrat PlanExecutor v1.0.0 (Partie 4 — Gestion des Erreurs).
Chaque exception correspond à un edge case documenté.
"""


class PlanExecutorError(Exception):
    """Exception de base pour toutes les erreurs PlanExecutor."""
    pass


class PlanExecutionInProgress(PlanExecutorError):
    """Levée quand execute_plan() est appelé alors qu'une exécution est déjà en cours.
    
    Edge case : EC-28 (exécution concurrente).
    Empêche la corruption silencieuse de self.step_results, self.plan, self.loop_count.
    """
    def __init__(self, message: str = "Une exécution est déjà en cours"):
        self.message = message
        super().__init__(self.message)


class CircularDependencyError(PlanExecutorError):
    """Levée quand le plan contient des dépendances circulaires.
    
    Edge case : EC-03 (dépendance circulaire).
    Détecté par DFS avant l'exécution du plan.
    """
    def __init__(self, step_a: int, step_b: int):
        self.step_a = step_a
        self.step_b = step_b
        self.message = f"Dépendance circulaire détectée: étape {step_a} -> {step_b}"
        super().__init__(self.message)


class AgentCreationError(PlanExecutorError):
    """Levée quand la création d'un agent SimpleAgent échoue.
    
    Edge case : EC-18 (agent creation fail).
    Empêche le crash non catché du processus.
    """
    def __init__(self, model: str, original_error: str):
        self.model = model
        self.original_error = original_error
        self.message = f"Impossible de créer l'agent pour le modèle '{model}': {original_error}"
        super().__init__(self.message)

class InvalidStepError(PlanExecutorError):
    """Levée quand une étape du plan est invalide.
    
    Edge cases : EC-02 (instruction manquante), EC-13 (file_path manquant).
    """
    def __init__(self, step_num, reason: str):
        self.step_num = step_num
        self.reason = reason
        self.message = f"Étape {step_num} invalide : {reason}"
        super().__init__(self.message)


class ModelSwapError(PlanExecutorError):
    """Levée quand le swap de modèle échoue.
    
    Edge case : EC-04 (swap échoue).
    """
    def __init__(self, model: str, step_num):
        self.model = model
        self.step_num = step_num
        self.message = f"Impossible de charger le modèle '{model}' pour l'étape {step_num}"
        super().__init__(self.message)


class LLMTimeoutError(PlanExecutorError):
    """Levée quand un appel LLM dépasse le timeout.
    
    Edge case : EC-07 (timeout LLM).
    """
    def __init__(self, model: str, timeout_s: int):
        self.model = model
        self.timeout_s = timeout_s
        self.message = f"Timeout après {timeout_s}s pour le modèle '{model}'"
        super().__init__(self.message)

class DuplicateStepError(PlanExecutorError):
    """Levée quand le plan contient des steps dupliqués.
    
    Edge case : EC-17 (steps dupliqués).
    """
    def __init__(self, step_num):
        self.step_num = step_num
        self.message = f"Step {step_num} apparaît plusieurs fois dans le plan"
        super().__init__(self.message)

class EmptyPlanError(PlanExecutorError):
    """Levée quand le plan généré est vide (déclenche le fallback minimal).
    
    Edge case : EC-01 (plan vide).
    Exception de documentation : le fallback est géré sans lever l'exception.
    """
    pass
