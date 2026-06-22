
import difflib, json, logging, os, shutil, subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Base racine du projet (dynamique) ────────────────
BASE_DIR = Path(__file__).resolve().parent
# =====================================================
import requests
from bs4 import BeautifulSoup
logger = logging.getLogger('devkit.tools')
SANDBOX = BASE_DIR
MODELS_DIR = Path(os.environ.get("REALIA_MODELS_DIR", str(BASE_DIR / "models")))
RAG_DIR = SANDBOX / 'rag'
SHELL_TIMEOUT = 30
HTTP_TIMEOUT = 15

def _check_sandbox(path):
    t = Path(path)
    if not t.is_absolute():
        t = SANDBOX / t
    try:
        t = t.resolve()
    except:
        return None
    s = str(t)
    if s.startswith(str(SANDBOX)) or s.startswith(str(MODELS_DIR)):
        return t
    return None

def read_file(path=None, filepath=None, mx=8000):
    if path is None and filepath is not None:
        path = filepath
    elif path is None:
        return {'success': False, 'output': '', 'error': 'path ou filepath requis'}
    t = _check_sandbox(path)
    if not t:
        return {'success': False, 'output': '', 'error': 'Hors sandbox'}
    if not t.exists():
        return {'success': False, 'output': '', 'error': 'Introuvable'}
    try:
        c = t.read_text(encoding='utf-8', errors='replace')
        if len(c) > mx:
            tr = chr(10) + '... [TRONQUE: ' + str(len(c)) + ' chars]'
            c = c[:mx] + tr
        return {'success': True, 'output': c, 'meta': {'path': str(t), 'lines': len(c.splitlines()), 'size': t.stat().st_size}}
    except Exception as e:
        return {'success': False, 'output': '', 'error': str(e)}

def write_file(path, content):
    t = _check_sandbox(path)
    if not t:
        return {'success': False, 'output': '', 'error': 'Hors sandbox'}
    try:
        t.parent.mkdir(parents=True, exist_ok=True)
        b = None
        if t.exists():
            b = str(t) + '.bak.realia'
            shutil.copy2(str(t), b)
        t.write_text(content, encoding='utf-8')
        return {'success': True, 'output': 'Ecrit: ' + str(t.stat().st_size) + ' o', 'meta': {'backup': b}}
    except Exception as e:
        return {'success': False, 'output': '', 'error': str(e)}

def list_files(path='.'):
    t = _check_sandbox(path) or SANDBOX
    if not t.exists():
        return {'success': False, 'output': '', 'error': 'Introuvable'}
    try:
        e = [(x.name, 'dir' if x.is_dir() else 'file', x.stat().st_size if x.is_file() else 0) for x in t.iterdir()]
        e.sort(key=lambda x: (x[1] != 'dir', x[0]))
        NL = chr(10)
        parts = ['  ' + a + ' ' * max(1, 30 - len(a)) + ('<DIR>' if b == 'dir' else str(c) + ' o') for a, b, c in e]
        o = NL.join(parts)
        return {'success': True, 'output': str(t) + ':' + NL + o, 'meta': {'count': len(e)}}
    except Exception as ex:
        return {'success': False, 'output': '', 'error': str(ex)}

def execute_shell_command(cmd=None, command=None):
    if cmd is None and command is not None:
        cmd = command
    for ch in '|;&':
        if ch in cmd:
            return {'success': False, 'output': '', 'error': 'Caractere dangereux: ' + repr(ch)}
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=SHELL_TIMEOUT, cwd=str(SANDBOX))
        o = r.stdout.strip()
        if r.stderr:
            o += chr(10) + '[stderr]' + chr(10) + r.stderr.strip()
        if len(o) > 4000:
            o = o[:4000] + chr(10) + '... [TRONQUE: ' + str(len(o)) + ' chars]'
        return {'success': r.returncode == 0, 'output': o or '(vide)', 'meta': {'returncode': r.returncode}}
    except subprocess.TimeoutExpired:
        return {'success': False, 'output': '', 'error': 'Timeout ' + str(SHELL_TIMEOUT) + 's'}
    except Exception as e:
        return {'success': False, 'output': '', 'error': str(e)}

def fetch_url_content(url, mx=5000):
    if not url.startswith(('http://', 'https://')):
        return {'success': False, 'output': '', 'error': 'URL invalide'}
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT, headers={'User-Agent': 'RealiaDevKit/0.9.0'})
        r.raise_for_status()
        ct = r.headers.get('Content-Type', '').lower()
        NL = chr(10)
        if 'html' in ct:
            s = BeautifulSoup(r.text, 'html.parser')
            for tag in s(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()
            o = NL.join(l for l in s.get_text(separator=NL, strip=True).splitlines() if l.strip())
        else:
            o = r.text
        if len(o) > mx:
            o = o[:mx] + NL + '... [TRONQUE: ' + str(len(o)) + ' chars]'
        return {'success': True, 'output': o, 'meta': {'url': url, 'status': r.status_code}}
    except Exception as e:
        return {'success': False, 'output': '', 'error': str(e)}

def query_rag(query, tk=3):
    p = RAG_DIR / 'index.jsonl'
    if not p.exists():
        return {'success': False, 'output': '', 'error': 'Pas d index RAG'}
    try:
        es = [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]
        if not es:
            return {'success': True, 'output': 'Aucune entree'}
        qw = set(query.lower().split())
        sc = [(sum(1 for w in qw if w in e.get('content', '').lower()), e) for e in es]
        sc.sort(key=lambda x: -x[0])
        top = [(s, e) for s, e in sc if s > 0][:tk]
        NL = chr(10)
        if not top:
            recent = es[-tk:]
            lines = ['Aucune correspondance. Entrees recentes:'] + ['  [' + e.get('type', '?') + '] ' + e.get('content', '')[:200] for e in recent]
            return {'success': True, 'output': NL.join(lines)}
        lines = ['Top ' + str(len(top)) + ' RAG:'] + ['  [Score:' + str(s) + '] ' + e.get('content', '')[:500] for s, e in top]
        return {'success': True, 'output': NL.join(lines), 'meta': {'results': len(top)}}
    except Exception as e:
        return {'success': False, 'output': '', 'error': str(e)}

TOOL_REGISTRY = {
    'read_file': read_file,
    'write_file': write_file,
    'list_files': list_files,
    'execute_shell': execute_shell_command,
    'fetch_url': fetch_url_content,
    'query_rag': query_rag,
}

def execute_tool(name, args):
    if name not in TOOL_REGISTRY:
        return {'success': False, 'output': '', 'error': 'Inconnu: ' + name}
    # Normaliser les noms de parametres (alias)
    # Qwen3 envoie filepath, mais write_file attend path
    param_aliases = {
        'filepath': 'path',
        'file': 'path',
        'cmd': 'command',
        'shell': 'command',
    }
    normalized = {}
    for k, v in args.items():
        k2 = param_aliases.get(k, k)
        normalized[k2] = v
    try:
        return TOOL_REGISTRY[name](**normalized)
    except Exception as e:
        return {'success': False, 'output': '', 'error': str(e)}
