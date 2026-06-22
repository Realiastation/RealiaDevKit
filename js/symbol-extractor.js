// ============================================
// SYMBOL EXTRACTOR — panel symboles fichier actif
// ============================================

class SymbolExtractor {
  constructor() {
    this._panel = null;
    this._symbols = [];
    this._paneId = 'left';
  }

  open(paneId) {
    this._paneId = paneId || this._activePane();
    this._render();
  }

  _activePane() {
    return window.paneState?.left?.active ? 'left' : 'right';
  }

  extract(content, language) {
    const patterns = this._patterns(language);
    const symbols = [];
    const lines = content.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      for (const p of patterns) {
        p.regex.lastIndex = 0;
        let m;
        while ((m = p.regex.exec(line)) !== null) {
          const name = m[1];
          if (name) {
            symbols.push({ name, type: p.type, line: i + 1, content: line.trim() });
          }
          if (m.index === p.regex.lastIndex) p.regex.lastIndex++;
        }
      }
    }
    this._symbols = symbols;
    return symbols;
  }

  _patterns(lang) {
    const base = { regex: /(?:def|class|function|const|let|var)\s+(\w+)/g, type: 'generic' };
    if (lang === 'python') return [
      { regex: /^\s*class\s+(\w+)/gm, type: 'class' },
      { regex: /^\s*(?:async\s+)?def\s+(\w+)/gm, type: 'function' },
      { regex: /^\s*@\w+/gm, type: 'decorator' },
      base
    ];
    if (lang === 'javascript' || lang === 'typescript') return [
      { regex: /(?:export\s+)?(?:function\s+)(\w+)/g, type: 'function' },
      { regex: /(?:export\s+)?(?:class\s+)(\w+)/g, type: 'class' },
      { regex: /(?:const|let|var)\s+(\w+)\s*=/g, type: 'variable' },
      base
    ];
    if (lang === 'yaml' || lang === 'yml') return [
      { regex: /^(\w[\w-]*):/gm, type: 'key' },
      base
    ];
    if (lang === 'html') return [
      { regex: /id="([\w-]+)"/g, type: 'id' },
      { regex: /class="([\w-]+)"/g, type: 'class' },
      base
    ];
    if (lang === 'bash' || lang === 'sh') return [
      { regex: /^(?:function\s+)?(\w+)\s*\(\)/gm, type: 'function' },
      base
    ];
    return [base];
  }

  _render() {
    const paneId = this._paneId;
    const paneStateItem = window.paneState?.[paneId];
    if (!paneStateItem || !paneStateItem.path) { this._showEmpty('Aucun fichier ouvert'); return; }
    const content = paneStateItem.content || '';
    const lang = this._detectLang(paneStateItem.path);
    if (!content) { this._showEmpty('Fichier vide'); return; }
    const symbols = this.extract(content, lang);
    if (!symbols.length) { this._showEmpty('Aucun symbole trouve (' + lang + ')'); return; }
    const groups = {};
    for (const s of symbols) { if (!groups[s.type]) groups[s.type] = []; groups[s.type].push(s); }
    this._renderPanel(groups, paneStateItem.path);
  }

  _renderPanel(groups, filePath) {
    const existing = document.getElementById('sym-panel');
    if (existing) existing.remove();
    const panel = document.createElement('div');
    panel.id = 'sym-panel';
    panel.style.cssText = 'position:fixed;top:60px;right:10px;width:260px;max-height:60vh;background:#1a1a2e;border:1px solid #444;border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,.6);z-index:7000;display:flex;flex-direction:column;overflow:hidden';
    const header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;padding:6px 10px;border-bottom:1px solid #333;gap:6px';
    header.innerHTML = '<span style="flex:1;color:#00bcd4;font-size:11px;font-weight:600">&#x1f523; Symboles</span><span style="font-size:10px;color:#888;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:120px">' + escapeHtml(filePath) + '</span><button onclick="se._closePanel()" style="background:#333;border:1px solid #555;color:#ccc;padding:1px 6px;border-radius:3px;cursor:pointer;font-size:10px">✕</button>';
    panel.appendChild(header);
    const body = document.createElement('div');
    body.style.cssText = 'flex:1;overflow-y:auto;padding:4px 0';
    let html = '';
    const icons = { class: '🔷', function: '⚡', variable: '📦', decorator: '@', id: '#', key: '🔑', accessor: '🔄', generic: '📌' };
    for (const [type, syms] of Object.entries(groups)) {
      const icon = icons[type] || '📌';
      html += '<div style="padding:2px 0"><div style="padding:3px 10px;font-size:10px;color:#888;font-weight:600">' + icon + ' ' + type + 's (' + syms.length + ')</div>';
      for (const s of syms) {
        html += '<div class="sym-item" onclick="se._goToLine(' + s.line + ')" onmouseover="this.style.background=\'#222\'" onmouseout="this.style.background=\'\'" style="padding:2px 10px 2px 14px;cursor:pointer;font-size:11px;color:#ccc;display:flex;gap:6px;align-items:baseline"><span style="color:#555;font-size:10px;min-width:26px;text-align:right">' + s.line + '</span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escapeHtml(s.name) + '</span></div>';
      }
      html += '</div>';
    }
    body.innerHTML = html;
    panel.appendChild(body);
    const footer = document.createElement('div');
    footer.style.cssText = 'padding:4px 10px;border-top:1px solid #333;font-size:10px;color:#555';
    footer.textContent = '⌨ Clic → scroll a la ligne';
    panel.appendChild(footer);
    document.body.appendChild(panel);
    this._panel = panel;
    this._keyHandler = (e) => { if (e.key === 'Escape') this._closePanel(); };
    document.addEventListener('keydown', this._keyHandler);
  }

  _showEmpty(msg) {
    const existing = document.getElementById('sym-panel');
    if (existing) existing.remove();
    const panel = document.createElement('div');
    panel.id = 'sym-panel';
    panel.style.cssText = 'position:fixed;top:60px;right:10px;width:220px;background:#1a1a2e;border:1px solid #444;border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,.6);z-index:7000;padding:12px;text-align:center;color:#888;font-size:11px';
    panel.innerHTML = '🔣 ' + escapeHtml(msg) + '<button onclick="se._closePanel()" style="display:block;margin:8px auto 0;background:#333;border:1px solid #555;color:#ccc;padding:2px 8px;border-radius:3px;cursor:pointer;font-size:10px">Fermer</button>';
    document.body.appendChild(panel);
    this._panel = panel;
    this._keyHandler = (e) => { if (e.key === 'Escape') this._closePanel(); };
    document.addEventListener('keydown', this._keyHandler);
  }

  _closePanel() {
    if (this._panel) { this._panel.remove(); this._panel = null; }
    if (this._keyHandler) { document.removeEventListener('keydown', this._keyHandler); this._keyHandler = null; }
  }

  _goToLine(line) {
    const paneId = this._activePane();
    const gutter = document.getElementById('pane-' + paneId + '-gutter');
    if (!gutter) return;
    const gutLines = gutter.querySelectorAll('span');
    for (let i = 0; i < gutLines.length; i++) {
      if (parseInt(gutLines[i].textContent) === line) {
        const target = gutLines[i].closest('.pane-line') || gutLines[i].parentElement;
        if (target) {
          target.scrollIntoView({ block: 'center' });
          const origBg = target.style.background;
          target.style.background = 'rgba(0,188,212,.2)';
          target.style.transition = 'background .6s';
          setTimeout(() => { target.style.background = origBg; }, 1500);
        }
        break;
      }
    }
  }

  _detectLang(path) {
    const ext = '.' + path.split('.').pop().toLowerCase();
    const map = { '.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.html': 'html', '.css': 'css', '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml', '.md': 'markdown', '.sh': 'bash', '.sql': 'sql', '.xml': 'xml' };
    return map[ext] || 'plaintext';
  }
}

const se = new SymbolExtractor();
window.se = se;
window.SymbolExtractor = SymbolExtractor;

document.addEventListener('keydown', (e) => {
  if (e.shiftKey && e.ctrlKey && e.key === 'O') { e.preventDefault(); se.open(); }
});

function escapeHtml(t) {
  return t.replace(/&/g,'&').replace(/</g,'<').replace(/>/g,'>').replace(/"/g,'"');
}
