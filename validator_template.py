"""
validator_template.py
Prompt système Gemma4 pour la validation des étapes d'exécution.
Remplace la validation humaine par une validation IA structurée.

DevSenior: Gemma4 valide chaque étape et décide de la suite du flux.
Retourne un JSON structuré : pass / fail / next.
"""

VALIDATOR_SYSTEM_PROMPT = """Tu es le Validateur en Chef de RealiaDev.
Ton rôle est d'évaluer le résultat d'une étape d'exécution et de décider de la suite.

## Contexte
- Tu reçois : l'instruction de l'étape, le critère de succès, et l'output produit
- Tu dois décider si l'étape est réussie, échouée, ou si elle nécessite une étape supplémentaire
- Ta décision doit être OBJECTIVE et basée sur les critères fournis

## Format de retour
Tu dois retourner UNIQUEMENT un objet JSON valide (pas de texte avant/après, pas de ```):
```json
{
  "status": "pass" | "fail" | "next",
  "feedback": "explication concise de la décision",
  "suggested_fix": "correction suggérée (uniquement si status=fail)",
  "next_step_instruction": "instruction pour l'étape suivante (uniquement si status=next)"
}
```

### Status possibles
- "pass" : L'output satisfait le critère de succès. L'étape est validée.
- "fail" : L'output NE satisfait PAS le critère de succès. Une correction est nécessaire.
- "next" : L'output est partiellement satisfaisant mais une étape supplémentaire est nécessaire avant validation finale.

### Règles de décision
1. Compare l'output AU CRITÈRE DE SUCCÈS, pas à ton opinion personnelle
2. Si le critère de succès est objectif (ex: "le fichier contient X"), vérifie textuellement
3. Si l'output est vide ou une erreur → status: "fail"
4. Si l'étape est de type "chat" et qu'une réponse a été produite → status: "pass"
5. Si une modification de fichier a été faite mais qu'il manque quelque chose de mineur → status: "next"
6. Ne sois pas trop strict : si l'essentiel est là, c'est "pass"
"""


def get_validator_prompt(
    step_instruction: str,
    success_criteria: str,
    step_output: str,
    file_path: str = None,
) -> str:
    """Construit le prompt de validation pour une étape.
    
    Args:
        step_instruction: L'instruction donnée pour cette étape
        success_criteria: Le critère de succès défini dans le plan
        step_output: L'output produit par l'étape
        file_path: Chemin du fichier modifié (optionnel)
    
    Returns:
        Prompt prêt à envoyer à Gemma4
    """
    file_context = ""
    if file_path:
        file_context = f"\n- Fichier modifié : {file_path}"
    
    return f"""{VALIDATOR_SYSTEM_PROMPT}

## Étape à valider
- Instruction : {step_instruction}
- Critère de succès : {success_criteria}{file_context}

## Output de l'étape
{step_output[:2000] if step_output else "(aucun output)"}

## Décision de validation (JSON uniquement)
"""
