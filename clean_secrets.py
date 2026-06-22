#!/usr/bin/env python3
"""
clean_secrets.py — Anonymisation & purge des secrets avant push officiel.

Utilisation :
    python3 clean_secrets.py              # Mode dry-run (affiche sans modifier)
    python3 clean_secrets.py --apply       # Applique les modifications
    python3 clean_secrets.py --restore     # Restaure depuis les backups .bak.realia

Actions :
    1. Anonymise les fichiers .env (remplace valeurs par placeholders)
    2. Ajoute .env à .gitignore si absent
    3. Scanne le dépôt pour des tokens hardcodés (sk-, hf_, ghp_, gho_)
    4. Purge les logs contenant des clés API
    5. Vérifie l'intégrité de LIVRAISON_BETA.md (si existe)

Statut : PRE-BETA — Script de sécurisation avant la release officielle (vendredi).
"""

import os
import re
import sys
import shutil
import json
from pathlib import Path
from datetime import datetime

# ── Configuration ──
REPO_ROOT = Path(__file__).resolve().parent
BACKUP_SUFFIX = ".bak.realia"
DRY_RUN = "--apply" not in sys.argv
RESTORE_MODE = "--restore" in sys.argv

# Variables d'environnement connues contenant des secrets
ENV_SECRET_KEYS = [
    "UTU_LLM_API_KEY",
    "JUDGE_LLM_API_KEY", 
    "GITHUB_TOKEN",
    "JINA_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "HF_TOKEN",
    "HUGGINGFACE_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
]

# Patterns de tokens hardcodés (regex)
TOKEN_PATTERNS = [
    (r'sk-[a-zA-Z0-9]{20,}', "OpenAI API Key (sk-)"),
    (r'hf_[a-zA-Z0-9]{20,}', "HuggingFace Token (hf_)"),
    (r'ghp_[a-zA-Z0-9]{20,}', "GitHub PAT (ghp_)"),
    (r'gho_[a-zA-Z0-9]{20,}', "GitHub OAuth (gho_)"),
    (r'ghu_[a-zA-Z0-9]{20,}', "GitHub User Token (ghu_)"),
    (r'xox[baprs]-[a-zA-Z0-9-]{10,}', "Slack Token (xox-)"),
    (r'AKIA[0-9A-Z]{16}', "AWS Access Key (AKIA)"),
]

# Extensions et chemins à ignorer
IGNORE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.ico',
                     '.woff', '.woff2', '.ttf', '.eot', '.otf',
                     '.mp3', '.mp4', '.wav', '.ogg',
                     '.zip', '.tar', '.gz', '.bz2', '.7z',
                     '.pdf', '.doc', '.docx', '.xls', '.xlsx',
                     '.gguf', '.bin', '.pt', '.pth', '.safetensors'}

IGNORE_DIRS = {'__pycache__', '.git', '.venv', 'venv', 'node_modules',
               'site-packages', 'cache_slots', 'logs', 'rag'}


def log(msg: str, level: str = "INFO") -> None:
    """Log structuré avec timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = {"INFO": "  •", "WARN": "  ⚠", "ERROR": "  ❌", "OK": "  ✅"}.get(level, "  •")
    print(f"[{ts}] {prefix} {msg}")


def backup_file(path: Path) -> bool:
    """Crée un backup .bak.realia si pas déjà fait."""
    backup_path = Path(str(path) + BACKUP_SUFFIX)
    if backup_path.exists():
        return False  # Backup déjà existant
    try:
        shutil.copy2(str(path), str(backup_path))
        log(f"Backup créé : {backup_path.name}", "OK")
        return True
    except Exception as e:
        log(f"Impossible de backuper {path.name} : {e}", "ERROR")
        return False


def restore_backups() -> int:
    """Restaure tous les fichiers depuis leurs backups .bak.realia."""
    count = 0
    for bak_path in REPO_ROOT.rglob(f"*{BACKUP_SUFFIX}"):
        original_path = Path(str(bak_path).replace(BACKUP_SUFFIX, ""))
        if bak_path.is_file():
            try:
                shutil.copy2(str(bak_path), str(original_path))
                bak_path.unlink()
                log(f"Restauration : {original_path.name}", "OK")
                count += 1
            except Exception as e:
                log(f"Échec restauration {original_path.name} : {e}", "ERROR")
    return count


def anonymize_env_files() -> int:
    """Anonymise les fichiers .env : remplace les vraies valeurs par des placeholders."""
    modified = 0
    
    # Chercher tous les fichiers .env (sauf .env.example)
    for env_file in REPO_ROOT.rglob(".env*"):
        if ".example" in env_file.name or not env_file.is_file():
            continue
        # Ignorer les dirs système
        if any(ign in env_file.parts for ign in IGNORE_DIRS):
            continue
            
        log(f"Analyse : {env_file.relative_to(REPO_ROOT)}")
        
        try:
            content = env_file.read_text(encoding="utf-8")
        except Exception:
            continue
        
        new_lines = []
        modified_lines = 0
        
        for line in content.splitlines():
            stripped = line.strip()
            # Ignorer commentaires et lignes vides
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
            
            # Vérifier si la ligne contient une variable secrète connue
            for secret_key in ENV_SECRET_KEYS:
                pattern = rf'^({secret_key})=(.*)$'
                match = re.match(pattern, stripped)
                if match:
                    var_name = match.group(1)
                    current_value = match.group(2)
                    # Ne pas toucher si déjà placeholder
                    if not current_value.startswith("${") and not current_value.startswith("CHANGEME_"):
                        placeholder = f"CHANGEME_{var_name}"
                        line = f"{var_name}={placeholder}"
                        modified_lines += 1
                        if not DRY_RUN:
                            log(f"  Anonymisé : {var_name}", "OK")
                        else:
                            log(f"  → Anonymiserait : {var_name}", "WARN")
                    break
            
            new_lines.append(line)
        
        if modified_lines > 0:
            if not DRY_RUN:
                backup_file(env_file)
                env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            modified += modified_lines
    
    return modified


def ensure_gitignore() -> int:
    """Ajoute .env et autres fichiers sensibles dans .gitignore si absents."""
    gitignore_path = REPO_ROOT / ".gitignore"
    
    required_entries = [
        "# === Secrets & credentials ===",
        ".env",
        ".env.*",
        "*.env",
        "credentials*",
        "cred*",
        "**/credentials",
        "*.pem",
        "*.key",
        "# === Logs ===",
        "logs/",
        "*.log",
        "# === Cache ===",
        "cache_slots/",
        "__pycache__/",
        "*.bak.realia",
    ]
    
    added = 0
    if not gitignore_path.exists():
        if DRY_RUN:
            log(f"→ Créerait .gitignore avec {len(required_entries)} entrées", "WARN")
            return len(required_entries)
        backup_file(gitignore_path)  # backup même si nouveau fichier
        gitignore_path.write_text("\n".join(required_entries) + "\n", encoding="utf-8")
        log(f".gitignore créé avec {len(required_entries)} entrées", "OK")
        return len(required_entries)
    
    existing = gitignore_path.read_text(encoding="utf-8").splitlines()
    
    for entry in required_entries:
        if entry.startswith("#"):
            continue
        if entry not in existing:
            if not DRY_RUN:
                # Ajouter avant le dernier saut de ligne
                with open(gitignore_path, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
                log(f"Ajouté à .gitignore : {entry}", "OK")
            else:
                log(f"→ Ajouterait à .gitignore : {entry}", "WARN")
            added += 1
    
    return added


def scan_hardcoded_tokens() -> list:
    """Scanne le dépôt pour des tokens hardcodés (sk-, hf_, ghp_, etc.)."""
    findings = []
    
    for filepath in REPO_ROOT.rglob("*"):
        # Filtres
        if not filepath.is_file():
            continue
        if any(ign in filepath.parts for ign in IGNORE_DIRS):
            continue
        if filepath.suffix.lower() in IGNORE_EXTENSIONS:
            continue
        # Ignorer les backups et fichiers binaires
        if filepath.name.endswith(BACKUP_SUFFIX):
            continue
        if filepath.stat().st_size > 1024 * 1024:  # > 1MB
            continue
        
        rel_path = filepath.relative_to(REPO_ROOT)
        
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        
        for pattern, label in TOKEN_PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                for token in matches:
                    # Masquer le token pour le log
                    masked = token[:8] + "..." + token[-4:] if len(token) > 12 else "[masqué]"
                    findings.append({
                        "file": str(rel_path),
                        "type": label,
                        "token_masked": masked,
                        "line": None,  # On ne localise pas la ligne précisément ici
                    })
                    log(f"Token trouvé : {label} dans {rel_path} ({masked})", "ERROR" if not DRY_RUN else "WARN")
    
    return findings


def purge_sensitive_logs() -> int:
    """Purger les logs qui contiennent des clés API."""
    logs_dir = REPO_ROOT / "logs"
    if not logs_dir.exists():
        return 0
    
    purged = 0
    for log_file in logs_dir.glob("*.jsonl"):
        if not log_file.is_file():
            continue
        
        try:
            content = log_file.read_text(encoding="utf-8")
        except Exception:
            continue
        
        # Vérifier si des tokens sont dans les logs
        has_secrets = False
        for pattern, label in TOKEN_PATTERNS:
            if re.search(pattern, content):
                has_secrets = True
                break
        
        # Vérifier aussi les valeurs des ENV_SECRET_KEYS
        if not has_secrets:
            for key in ENV_SECRET_KEYS:
                if re.search(rf'(?:{key})\s*[:=]\s*\S+', content):
                    has_secrets = True
                    break
        
        if has_secrets:
            if not DRY_RUN:
                backup_file(log_file)
                # Nettoyer les lignes : remplacer les tokens par [REDACTED]
                new_lines = []
                for line in content.splitlines():
                    for pattern, label in TOKEN_PATTERNS:
                        line = re.sub(pattern, "[REDACTED_TOKEN]", line)
                    for key in ENV_SECRET_KEYS:
                        line = re.sub(
                            rf'({key})\s*[:=]\s*\S+',
                            r'\1= [REDACTED]',
                            line
                        )
                    new_lines.append(line)
                log_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                log(f"Logs purgés : {log_file.name}", "OK")
            else:
                log(f"→ Purgerait les secrets de : {log_file.name}", "WARN")
            purged += 1
    
    return purged


def check_livraison_integrity() -> dict:
    """Vérifie que LIVRAISON_BETA.md n'est pas cassé."""
    livraison_path = REPO_ROOT / "LIVRAISON_BETA.md"
    result = {"exists": False, "ok": False, "issues": []}
    
    if not livraison_path.exists():
        result["exists"] = False
        result["ok"] = True  # Pas de fichier à casser
        log("LIVRAISON_BETA.md non trouvé (aucune vérification nécessaire)", "INFO")
        return result
    
    result["exists"] = True
    
    try:
        content = livraison_path.read_text(encoding="utf-8")
        
        # Vérifications
        if not content.strip():
            result["issues"].append("Fichier vide")
        
        if len(content) < 100:
            result["issues"].append("Fichier anormalement court (< 100 chars)")
        
        # Vérifier que les fichiers référencés existent
        refs = re.findall(r'`([^`]+)`', content)
        for ref in refs:
            # Ne vérifier que les chemins de fichiers
            if '/' in ref or ref.endswith('.py') or ref.endswith('.sh') or ref.endswith('.md'):
                candidate = REPO_ROOT / ref
                if not candidate.exists():
                    result["issues"].append(f"Référence manquante : {ref}")
        
        result["ok"] = len(result["issues"]) == 0
        
        if result["ok"]:
            log("LIVRAISON_BETA.md : intégrité vérifiée ✅", "OK")
        else:
            for issue in result["issues"]:
                log(f"LIVRAISON_BETA.md : {issue}", "WARN")
    
    except Exception as e:
        result["issues"].append(f"Erreur de lecture : {e}")
        result["ok"] = False
        log(f"LIVRAISON_BETA.md : erreur de lecture : {e}", "ERROR")
    
    return result


def main() -> int:
    """Point d'entrée principal."""
    print("=" * 60)
    print("  🔒 clean_secrets.py — Anonymisation & Purge")
    print(f"  Mode : {'DRY-RUN' if DRY_RUN else 'APPLICATION'} ")
    print(f"  Cible : {REPO_ROOT}")
    print("=" * 60)
    print()
    
    if RESTORE_MODE:
        print("🔄 Mode RESTAURATION des backups...")
        count = restore_backups()
        log(f"{count} fichier(s) restauré(s)", "OK")
        return 0
    
    # ── 1. Anonymisation des .env ──
    print("📁 Étape 1/5 : Anonymisation des fichiers .env")
    env_modified = anonymize_env_files()
    if env_modified > 0:
        log(f"{env_modified} variable(s) anonymisée(s)", "OK")
    else:
        log("Aucune variable à anonymiser", "INFO")
    print()
    
    # ── 2. Sécurisation .gitignore ──
    print("📁 Étape 2/5 : Sécurisation du .gitignore")
    gitignore_added = ensure_gitignore()
    if gitignore_added > 0:
        log(f"{gitignore_added} entrée(s) ajoutée(s)", "OK")
    else:
        log(".gitignore déjà à jour", "INFO")
    print()
    
    # ── 3. Scan des tokens hardcodés ──
    print("🔍 Étape 3/5 : Scan des tokens hardcodés")
    findings = scan_hardcoded_tokens()
    if findings:
        log(f"{len(findings)} token(s) détecté(s) dans les fichiers", "ERROR")
        if not DRY_RUN:
            # Sauvegarder le rapport
            report_path = REPO_ROOT / "secret_scan_report.json"
            report_path.write_text(
                json.dumps(findings, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            log(f"Rapport sauvegardé : secret_scan_report.json", "OK")
    else:
        log("Aucun token hardcodé détecté ✅", "OK")
    print()
    
    # ── 4. Purge des logs sensibles ──
    print("🧹 Étape 4/5 : Purge des logs sensibles")
    purged = purge_sensitive_logs()
    if purged > 0:
        log(f"{purged} fichier(s) de logs purgé(s)", "OK")
    else:
        log("Aucun log sensible trouvé", "INFO")
    print()
    
    # ── 5. Vérification LIVRAISON_BETA.md ──
    print("📄 Étape 5/5 : Vérification LIVRAISON_BETA.md")
    integrity = check_livraison_integrity()
    if not integrity["ok"]:
        log("⚠️ Intégrité à vérifier manuellement", "WARN" if DRY_RUN else "ERROR")
    print()
    
    # ── Rapport final ──
    print("=" * 60)
    print("  📊 RAPPORT FINAL")
    print(f"  Variables .env anonymisées : {env_modified}")
    print(f"  Entrées .gitignore ajoutées : {gitignore_added}")
    print(f"  Tokens hardcodés détectés : {len(findings)}")
    print(f"  Logs purgés : {purged}")
    print(f"  LIVRAISON_BETA.md : {'✅ OK' if integrity['ok'] else '⚠️ Problèmes'}")
    print(f"  Mode : {'🔍 DRY-RUN (ajouter --apply pour exécuter)' if DRY_RUN else '✅ APPLIQUÉ'}")
    print("=" * 60)
    
    if DRY_RUN and (env_modified > 0 or gitignore_added > 0 or findings or purged > 0):
        print("\n  💡 Relance avec --apply pour appliquer les modifications.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
