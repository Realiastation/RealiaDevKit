// ============================================
// DIFF VIEWER — Parse unified diff → side-by-side
// ============================================
// Synchronisé avec highlight.js pour la coloration
// ============================================

class DiffViewer {
  constructor() {
    this._modal = null;
    this._maxLines = 5000;
  }

  // ── Open diff for a file ─────────────────
  async open(path) {
    try {
      const r = await fetch(`/api/git/diff?path=${encodeURIComponent(path)}`);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      this._show(d.diff, path);
    } catch(e) {
      this._showError(`Impossible de charger le diff pour ${path} : ${e.message}`);
    }
  }

  // ── Parse unified diff → lines structurées ──
  _parse(diffText) {
    const lines = diffText.split('\n');
    const MAX = this._maxLines;
    let truncated = false;

    // Skip header lines (---/+++)
    let i = 0;
    const hunks = [];
    let currentHunk = null;

    if (lines.length > MAX + 50) {
      truncated = true;
      lines.length = MAX + 50;
    }

    for (; i < lines.length; i++) {
      const line = lines[i];

      // Hunk header @@ -a,b +c,d @@
      if (line.startsWith('@@')) {
        if (currentHunk) hunks.push(currentHunk);
        const m = line.match(/@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
        currentHunk = {
          oldStart: m ? parseInt(m[1]) : 0,
          oldLines: m && m[2] ? parseInt(m[2]) : 1,
          newStart: m ? parseInt(m[3]) : 0,
          newLines: m && m[4] ? parseInt(m[4]) : 1,
          lines: []
        };
        continue;
      }

      if (!currentHunk) continue;

      if (line.startsWith('+')) {
        currentHunk.lines.push({ type: 'add', content: line.slice(1) });
      } else if (line.startsWith('-')) {
        currentHunk.lines.push({ type: 'del', content: line.slice(1) });
      } else if (line.startsWith(' ')) {
        currentHunk.lines.push({ type: 'ctx', content: line.slice(1) });
      }
      // Ignorer \ No newline at end of file
    }
    if (currentHunk) hunks.push(currentHunk);

    return { hunks, truncated };
  }

  // ── Render modal ──────────────────────────
  _show(diffText, path) {
    // Fermer modal existant
    this._close();

    const parsed = this._parse(diffText);
    const modal = document.createElement('div');
    modal.className = 'dv-modal';
    modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.7);z-index:9000;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(2px)';
    modal.onclick = (e) => { if (e.target === modal) this._close(); };

    const container = document.createElement('div');
    container.className = 'dv-container';
    container.style.cssText = 'background:#1a1a2e;border:1px solid #444;border-radius:8px;width:90%;max-width:1200px;max-height:85vh;display:flex;flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.7)';

    // Header
    const header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;padding:10px 14px;border-bottom:1px solid #333;gap:10px';
    header.innerHTML = `
      <span style="flex:1;color:#00bcd4;font-size:13px;font-weight:600">📄 ${escapeHtml(path)}</span>
      <span style="font-size:11px;color:#888">HEAD ↔ Working Tree</span>
      <button onclick="diffViewer._close()" style="background:#333;border:1px solid #555;color:#ccc;padding:2px 8px;border-radius:4px;cursor:pointer;font-size:12px">✕</button>
    `;
    container.appendChild(header);

    // Avertissement truncation
    if (parsed.truncated) {
      const warn = document.createElement('div');
      warn.style.cssText = 'padding:6px 14px;background:#332b00;color:#ffb74d;font-size:11px;border-bottom:1px solid #555';
      warn.textContent = `⚠ Fichier volumineux : affichage limité à ${this._maxLines} lignes. Ouvrir dans l'éditeur pour le contenu complet.`;
      container.appendChild(warn);
    }

    // Corps : deux panneaux
    const body = document.createElement('div');
    body.style.cssText = 'flex:1;overflow:hidden;display:flex;min-height:0';

    // Defines which side each line goes on
    const leftLines = [];
    const rightLines = [];

    let oldLineNum = parsed.hunks[0]?.oldStart || 1;
    let newLineNum = parsed.hunks[0]?.newStart || 1;

    for (const hunk of parsed.hunks) {
      // Gap marker
      leftLines.push({ type: 'gap', num: '...' });
      rightLines.push({ type: 'gap', num: '...' });

      for (const line of hunk.lines) {
        if (line.type === 'del') {
          leftLines.push({ type: 'del', num: oldLineNum++, content: line.content, side: 'left' });
          rightLines.push({ type: 'empty', num: '' });
        } else if (line.type === 'add') {
          leftLines.push({ type: 'empty', num: '' });
          rightLines.push({ type: 'add', num: newLineNum++, content: line.content, side: 'right' });
        } else {
          leftLines.push({ type: 'ctx', num: oldLineNum++, content: line.content, side: 'both' });
          rightLines.push({ type: 'ctx', num: newLineNum++, content: line.content, side: 'both' });
        }
      }
    }

    const paneLeft = this._createPane(leftLines, 'left', path);
    const paneRight = this._createPane(rightLines, 'right', path);
    body.appendChild(paneLeft);
    body.appendChild(paneRight);

    // Sync scroll
    paneLeft.addEventListener('scroll', () => {
      paneRight.scrollTop = paneLeft.scrollTop;
      paneRight.scrollLeft = paneLeft.scrollLeft;
    });
    paneRight.addEventListener('scroll', () => {
      paneLeft.scrollTop = paneRight.scrollTop;
      paneLeft.scrollLeft = paneRight.scrollLeft;
    });

    container.appendChild(body);

    // Footer
    const footer = document.createElement('div');
    footer.style.cssText = 'display:flex;gap:12px;padding:6px 14px;border-top:1px solid #333;font-size:11px;color:#888';
    footer.innerHTML = `
      <span style="color:#f44336">− ${leftLines.filter(l => l.type === 'del').length} suppressions</span>
      <span style="color:#4caf50">+ ${rightLines.filter(l => l.type === 'add').length} ajouts</span>
      <span style="color:#888">${parsed.hunks.length} segments</span>
    `;
    container.appendChild(footer);

    modal.appendChild(container);
    document.body.appendChild(modal);
    this._modal = modal;

    // Gérer Escape
    this._keyHandler = (e) => { if (e.key === 'Escape') this._close(); };
    document.addEventListener('keydown', this._keyHandler);
  }

  _createPane(lines, side, path) {
    const pane = document.createElement('div');
    pane.className = 'dv-pane';
    pane.style.cssText = 'flex:1;overflow:auto;font-family:\'JetBrains Mono\',monospace;font-size:12px;line-height:1.5;background:#0d0d1a';

    let html = '';
    let lineCounter = 0;
    for (const line of lines) {
      if (line.type === 'empty') {
        html += `<div class="dv-line dv-empty"><span class="dv-num"></span><span class="dv-code"></span></div>`;
        continue;
      }
      if (line.type === 'gap') {
        html += `<div class="dv-line dv-gap"><span class="dv-num">...</span><span class="dv-code"></span></div>`;
        continue;
      }
      const cls = line.type === 'del' ? 'dv-del' : line.type === 'add' ? 'dv-add' : '';
      const content = escapeHtml(line.content || '');
      html += `<div class="dv-line ${cls}"><span class="dv-num">${line.num}</span><span class="dv-code">${content}</span></div>`;
      lineCounter++;
    }

    pane.innerHTML = html;
    return pane;
  }

  _showError(msg) {
    const modal = document.createElement('div');
    modal.className = 'dv-modal';
    modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.7);z-index:9000;display:flex;align-items:center;justify-content:center';
    modal.innerHTML = `<div style="background:#1a1a2e;border:1px solid #444;border-radius:8px;padding:20px 30px;max-width:500px">
      <div style="color:#f44336;font-size:14px;margin-bottom:8px">❌ Erreur</div>
      <div style="color:#ccc;font-size:12px">${escapeHtml(msg)}</div>
      <button onclick="this.closest('.dv-modal').remove()" style="margin-top:12px;background:#333;color:#ccc;border:1px solid #555;padding:4px 12px;border-radius:4px;cursor:pointer">Fermer</button>
    </div>`;
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    document.body.appendChild(modal);
    this._modal = modal;
  }

  _close() {
    if (this._modal) {
      this._modal.remove();
      this._modal = null;
    }
    if (this._keyHandler) {
      document.removeEventListener('keydown', this._keyHandler);
      this._keyHandler = null;
    }
  }
}

// ── Instance globale ──
const diffViewer = new DiffViewer();

// ── Helper pour l'appel depuis git-panel ──
function openDiffViewer(path) {
  diffViewer.open(path);
}

// Export
window.diffViewer = diffViewer;
window.openDiffViewer = openDiffViewer;

function escapeHtml(t) {
  return t.replace(/&/g,'&').replace(/</g,'<').replace(/>/g,'>').replace(/"/g,'"');
}
