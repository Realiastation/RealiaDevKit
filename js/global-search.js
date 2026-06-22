// ============================================
// GLOBAL SEARCH — Ctrl+Shift+F, debounce, groupé
// ============================================

const GS_API = (window.REALIA_CONFIG?.API_BASE || 'http://localhost:8095') + '/api/search';



class GlobalSearch {
  constructor() {
    this._overlay = null;
    this._timer = null;
    this._query = '';
    this._results = [];
    this._selectedIdx = -1;
    this._abort = false;
    this._active = false;
  }

  // ── Open overlay ────────────────────────
  open() {
    this._close();
    this._active = true;

    const overlay = document.createElement('div');
    overlay.id = 'gs-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);backdrop-filter:blur(3px);z-index:8000;display:flex;align-items:flex-start;justify-content:center;padding-top:60px';
    overlay.onclick = (e) => { if (e.target === overlay) this._close(); };

    const container = document.createElement('div');
    container.style.cssText = 'background:#1e1e2e;border:1px solid #444;border-radius:8px;width:640px;max-height:460px;display:flex;flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.7)';

    // Search bar
    const bar = document.createElement('div');
    bar.style.cssText = 'display:flex;gap:6px;padding:8px 10px;border-bottom:1px solid #444;align-items:center';
    bar.innerHTML = `
      <input id="gs-input" placeholder="Rechercher dans le projet..." style="flex:1;background:#2a2a3e;color:#ddd;border:1px solid #555;padding:8px 10px;border-radius:4px;font-family:'JetBrains Mono',monospace;font-size:13px;outline:none" autofocus />
      <button id="gs-case" class="gs-toggle" title="Case sensitive" style="background:#222;color:#888;border:1px solid #444;padding:4px 7px;border-radius:3px;cursor:pointer;font-size:11px">Aa</button>
      <button id="gs-regex" class="gs-toggle" title="Expression régulière" style="background:#222;color:#888;border:1px solid #444;padding:4px 7px;border-radius:3px;cursor:pointer;font-size:11px">.*</button>
      <button id="gs-word" class="gs-toggle" title="Mot entier" style="background:#222;color:#888;border:1px solid #444;padding:4px 7px;border-radius:3px;cursor:pointer;font-size:11px">ab</button>
      <span id="gs-stats" style="font-size:11px;color:#555;min-width:50px;text-align:right"></span>
    `;
    container.appendChild(bar);

    // Results list
    const list = document.createElement('div');
    list.id = 'gs-list';
    list.style.cssText = 'flex:1;overflow-y:auto;padding:2px 0';
    list.innerHTML = '<div style="padding:14px;text-align:center;color:#555;font-size:12px">Tapez pour rechercher...</div>';
    container.appendChild(list);

    // Footer
    const footer = document.createElement('div');
    footer.style.cssText = 'display:flex;gap:16px;padding:6px 10px;border-top:1px solid #333;font-size:10px;color:#666';
    footer.innerHTML = `<span>↵ Ouvrir</span><span>↑↓ Naviguer</span><span>Ctrl+Click → Panneau droit</span><span>Esc Fermer</span>`;
    container.appendChild(footer);

    overlay.appendChild(container);
    document.body.appendChild(overlay);
    this._overlay = overlay;

    // Focus & events
    const input = document.getElementById('gs-input');
    setTimeout(() => input?.focus(), 50);

    // Toggles
    document.querySelectorAll('.gs-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        btn.classList.toggle('gs-active');
        btn.style.background = btn.classList.contains('gs-active') ? '#0d47a1' : '#222';
        btn.style.color = btn.classList.contains('gs-active') ? '#fff' : '#888';
        if (this._query) this._search();
      });
    });

    // Input debounce
    input.addEventListener('input', (e) => {
      this._query = e.target.value.trim();
      if (this._timer) clearTimeout(this._timer);
      this._timer = setTimeout(() => this._search(), 300);
    });

    // Keyboard navigation
    input.addEventListener('keydown', (e) => this._handleKey(e));
    list.addEventListener('keydown', (e) => this._handleKey(e));

    // Escape
    this._keyHandler = (e) => {
      if (e.key === 'Escape') this._close();
      else if (e.key === 'Enter') this._openSelected();
    };
    document.addEventListener('keydown', this._keyHandler);

    this._schedulePreview();
  }

  // ── Search ───────────────────────────────
  async _search() {
    const q = this._query;
    if (!q) {
      this._clearResults();
      return;
    }

    const caseSens = document.getElementById('gs-case')?.classList.contains('gs-active') || false;
    const useRegex = document.getElementById('gs-regex')?.classList.contains('gs-active') || false;
    const wholeWord = document.getElementById('gs-word')?.classList.contains('gs-active') || false;

    const list = document.getElementById('gs-list');
    list.innerHTML = '<div style="padding:14px;text-align:center"><span class="spinner"></span></div>';

    try {
      const r = await fetch(`${GS_API}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, case_sensitive: caseSens, use_regex: useRegex, match_whole_word: wholeWord })
      });
      if (!r.ok) {
        const d = await r.json();
        list.innerHTML = `<div style="padding:14px;text-align:center;color:#f44336;font-size:12px">${escapeHtml(d.detail || 'Erreur')}</div>`;
        return;
      }
      const d = await r.json();
      this._showResults(d);
    } catch(e) {
      list.innerHTML = `<div style="padding:14px;text-align:center;color:#f44336;font-size:12px">${escapeHtml(e.message)}</div>`;
    }
  }

  _showResults(data) {
    const { results, total_matches, searched_files, truncated } = data;
    const list = document.getElementById('gs-list');
    const stats = document.getElementById('gs-stats');
    stats.textContent = `🔍 ${total_matches}`;

    if (!results.length) {
      list.innerHTML = `<div style="padding:14px;text-align:center;color:#888;font-size:12px">Aucun résultat (${searched_files} fichiers parcourus)</div>`;
      return;
    }

    // Group by file
    const groups = {};
    for (const r of results) {
      if (!groups[r.file]) groups[r.file] = [];
      groups[r.file].push(r);
    }

    let html = '';
    this._results = [];
    let idx = 0;
    for (const [file, lines] of Object.entries(groups)) {
      html += `<div class="gs-group" style="padding:2px 0"><div class="gs-file" style="padding:4px 10px;font-size:11px;color:#00bcd4;font-weight:600;cursor:pointer" onclick="gs._openFile('${escapeHtml(file).replace(/'/g,"\\'")}')">📄 ${escapeHtml(file)}</div>`;
      for (const l of lines) {
        const ctx = escapeHtml(l.content);
        const lineNum = l.line;
        const entry = { file: l.file, line: lineNum };
        this._results.push(entry);
        html += `<div class="gs-result" data-idx="${idx}" onclick="gs._openResult(${idx})" onmouseover="this.style.background='#222'" onmouseout="this.style.background=''" style="padding:2px 10px 2px 20px;cursor:pointer;font-size:11px;color:#ccc;display:flex;gap:8px;align-items:baseline"><span style="color:#555;min-width:32px;text-align:right;font-size:10px">${lineNum}</span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">${ctx}</span></div>`;
        idx++;
      }
      html += `</div>`;
    }

    if (truncated) {
      html += `<div style="padding:8px 10px;color:#ffb74d;font-size:10px">⚠ Limité à 100 résultats (${searched_files} fichiers parcourus)</div>`;
    }

    list.innerHTML = html;
    this._selectedIdx = -1;
  }

  _clearResults() {
    const list = document.getElementById('gs-list');
    const stats = document.getElementById('gs-stats');
    if (list) list.innerHTML = '<div style="padding:14px;text-align:center;color:#555;font-size:12px">Tapez pour rechercher...</div>';
    if (stats) stats.textContent = '';
    this._results = [];
    this._selectedIdx = -1;
  }

  // ── Navigation ───────────────────────────
  _handleKey(e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); this._navigate(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); this._navigate(-1); }
    else if (e.key === 'Enter') { e.preventDefault(); this._openSelected(); }
  }

  _navigate(dir) {
    if (!this._results.length) return;
    this._selectedIdx = Math.max(0, Math.min(this._results.length - 1, this._selectedIdx + dir));
    this._highlightSelected();
  }

  _highlightSelected() {
    document.querySelectorAll('.gs-result').forEach(el => {
      const idx = parseInt(el.dataset.idx);
      el.style.background = idx === this._selectedIdx ? '#0d47a1' : '';
      el.style.color = idx === this._selectedIdx ? '#fff' : '#ccc';
      if (idx === this._selectedIdx) el.scrollIntoView({ block: 'nearest' });
    });
  }

  async _openSelected() {
    if (this._selectedIdx >= 0 && this._selectedIdx < this._results.length) {
      await this._openResult(this._selectedIdx);
    }
  }

  async _openResult(idx) {
    const entry = this._results[idx];
    if (!entry) return;
    await this._openFile(entry.file, entry.line);
  }

  async _openFile(file, line) {
    this._close();
    // Trouver l'élément dans l'explorateur
    const li = document.querySelector(`#fileUl li[data-path="${escapeHtml(file)}"]`);
    if (li && typeof selectFile === 'function') {
      await selectFile(li, file);
    } else {
      // Fallback vers API
      const pane = paneState.left.active ? 'left' : 'right';
      await openFileInPane(file, pane);
    }
    // Scroll to line
    setTimeout(() => _gsScrollToLine(file, line), 400);
  }

  _close() {
    if (this._overlay) {
      this._overlay.remove();
      this._overlay = null;
    }
    if (this._keyHandler) {
      document.removeEventListener('keydown', this._keyHandler);
      this._keyHandler = null;
    }
    this._active = false;
  }
}

// ── Scroll helper ──────────────────────────
function _gsScrollToLine(file, line) {
  // Cherche la ligne dans le panneau actif
  const activePane = paneState.left.active ? 'left' : 'right';
  const codeEl = document.getElementById(`pane-${activePane}-code`);
  if (!codeEl) return;
  const lines = codeEl.querySelectorAll('.hljs-ln-line, .hljs-ln-numbers');
  // Parser les numéros de ligne
  const gutterEl = document.getElementById(`pane-${activePane}-gutter`);
  if (gutterEl) {
    const gutLines = gutterEl.querySelectorAll('span');
    for (let i = 0; i < gutLines.length; i++) {
      if (parseInt(gutLines[i].textContent) === line) {
        const scrollWrap = document.getElementById(`pane-${activePane}-scroll-wrap`);
        if (scrollWrap) {
          const target = gutLines[i].closest('.pane-line') || gutLines[i].parentElement;
          if (target) target.scrollIntoView({ block: 'center' });
          // Highlight temporaire
          target.style.background = 'rgba(0,188,212,.15)';
          setTimeout(() => { target.style.background = ''; }, 1000);
        }
        break;
      }
    }
  }
}

// ── Instance globale ────────────────────────
const gs = new GlobalSearch();
window.gs = gs;
window.GlobalSearch = GlobalSearch;

// ── Keyboard shortcut Registrierung ────────
document.addEventListener('keydown', (e) => {
  if (e.shiftKey && e.ctrlKey && e.key === 'F') {
    e.preventDefault();
    gs.open();
  }
});
