// ============================================
// SPLIT VIEW — Éditeur en panneaux partagés
// ============================================
// vertical split, resizer, sync scroll, raccourcis clavier
// ============================================

const paneState = {
  left: { path: null, content: '', active: true, savedAt: Date.now() },
  right: { path: null, content: '', active: false, savedAt: Date.now() }
};
let _splitActive = false;
let _syncScrollEnabled = false;
let _isSplitResizing = false;

// --- Toggle split ---
function toggleSplit(mode = 'vertical') {
  const container = document.getElementById('editor-split-container');
  const rightPane = document.getElementById('pane-right');
  const resizer = document.getElementById('split-resizer');
  if (!container || !rightPane || !resizer) return;

  _splitActive = !_splitActive;
  if (_splitActive) {
    container.classList.remove('single');
    container.classList.add('split', mode);
    rightPane.classList.remove('hidden');
    resizer.classList.remove('hidden');
    // Focus le panneau droit s'il existe, sinon gauche
    setActivePane('right');
    document.getElementById('btnToggleSplit').textContent = '⊞ Split Off';
    document.getElementById('btnToggleSplit').classList.add('active');
  } else {
    container.classList.remove('split', mode);
    container.classList.add('single');
    rightPane.classList.add('hidden');
    resizer.classList.add('hidden');
    setActivePane('left');
    document.getElementById('btnToggleSplit').textContent = '⊞ Split';
    document.getElementById('btnToggleSplit').classList.remove('active');
  }
}

// --- Focus pane ---
function setActivePane(paneId) {
  if (!_splitActive && paneId === 'right') return;
  paneState.left.active = (paneId === 'left');
  paneState.right.active = (paneId === 'right');
  document.getElementById('pane-left').classList.toggle('focused', paneId === 'left');
  document.getElementById('pane-right').classList.toggle('focused', paneId === 'right');
  // Mettre à jour le currentPath global
  const p = paneState[paneId];
  if (p?.path) {
    STATE.currentPath = p.path;
    STATE.currentContent = p.content || '';
    document.getElementById('currentFile').textContent = p.path;
  }
}

// --- Resizer ---
function initSplitResizer() {
  const resizer = document.getElementById('split-resizer');
  if (!resizer) return;

  resizer.addEventListener('mousedown', (e) => {
    _isSplitResizing = true;
    const container = document.getElementById('editor-split-container');
    const left = document.getElementById('pane-left');
    const right = document.getElementById('pane-right');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const startX = e.clientX;
    const startFlex = left.style.flex ? parseFloat(left.style.flex) : 1;

    const onMove = (ev) => {
      if (!_isSplitResizing) return;
      const dx = ev.clientX - startX;
      const containerW = container.offsetWidth;
      const ratio = (containerW / 2 + dx) / containerW;
      const clamped = Math.max(0.2, Math.min(0.8, ratio));
      left.style.flex = clamped;
      right.style.flex = 1 - clamped;
      requestAnimationFrame(() => {}); // throttle friendly
    };

    const onUp = () => {
      _isSplitResizing = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

// --- Open file in a specific pane ---
async function openFileInPane(path, paneId) {
  if (!path) return;
  const pane = paneState[paneId];
  if (!pane) return;

  // Load content
  let content;
  try {
    content = await loadFileWithCache(path);
  } catch (e) {
    content = '// Erreur: ' + e.message;
  }

  pane.path = path;
  pane.content = content;
  pane.active = true;

  const prefix = 'pane-' + paneId;
  const codeEl = document.getElementById(prefix + '-code');
  const gutterEl = document.getElementById(prefix + '-gutter');
  const textareaEl = document.getElementById(prefix + '-textarea');
  const headerEl = document.getElementById(prefix + '-header-path');

  if (codeEl) {
    const lang = _langFromPath(path);
    codeEl.className = 'language-' + lang;
    codeEl.textContent = content;
    try { hljs.highlightElement(codeEl); } catch(e) {}
  }
  if (gutterEl) {
    const lines = content.split('\n');
    gutterEl.innerHTML = lines.map((_, i) => '<div style="line-height:1.5">' + (i + 1) + '</div>').join('');
  }
  if (textareaEl) {
    textareaEl.value = content;
    textareaEl.classList.remove('hidden');
  }
  if (headerEl) {
    headerEl.textContent = path.split('/').pop() || path;
  }

  // Crash recovery
  const recovered = await tryRecover(path);
  if (recovered) {
    pane.content = recovered;
    if (codeEl) codeEl.textContent = recovered;
    if (textareaEl) textareaEl.value = recovered;
    _setPaneSaveIndicator(paneId, 'local');
  }

  setActivePane(paneId);
}

// --- Close pane ---
function closePane(paneId) {
  if (paneId === 'left') {
    // Vider le panneau gauche
    paneState.left = { path: null, content: '', active: false, savedAt: Date.now() };
    document.getElementById('pane-left-code').textContent = '';
    document.getElementById('pane-left-gutter').innerHTML = '';
    document.getElementById('pane-left-textarea').value = '';
    document.getElementById('pane-left-textarea').classList.add('hidden');
    document.getElementById('pane-left-header-path').textContent = 'Aucun fichier';
  } else {
    paneState.right = { path: null, content: '', active: false, savedAt: Date.now() };
    toggleSplit(); // désactive le split
  }
}

// --- Sync scroll & indicator ---
function toggleSyncScroll() {
  _syncScrollEnabled = !_syncScrollEnabled;
  const btn = document.getElementById('btnSyncScroll');
  if (btn) {
    btn.textContent = _syncScrollEnabled ? '🔄 Sync ON' : '🔄 Sync OFF';
    btn.classList.toggle('active', _syncScrollEnabled);
  }
}

function _syncScrollPane(srcPaneId) {
  if (!_syncScrollEnabled) return;
  const targetId = srcPaneId === 'left' ? 'right' : 'left';
  const srcWrap = document.getElementById('pane-' + srcPaneId + '-scroll-wrap');
  const tgtWrap = document.getElementById('pane-' + targetId + '-scroll-wrap');
  if (!srcWrap || !tgtWrap) return;
  const ratio = srcWrap.scrollTop / (srcWrap.scrollHeight - srcWrap.clientHeight || 1);
  tgtWrap.scrollTop = ratio * (tgtWrap.scrollHeight - tgtWrap.clientHeight);
}

// --- Pane save indicator ---
function _setPaneSaveIndicator(paneId, status) {
  const el = document.getElementById('pane-' + paneId + '-save-indicator');
  if (!el) return;
  switch (status) {
    case 'saved': el.textContent = '🟢'; el.style.color = '#4caf50'; break;
    case 'saving': el.textContent = '🟡'; el.style.color = '#ff9800'; break;
    case 'local': el.textContent = '🔵'; el.style.color = '#42a5f5'; break;
    default: el.textContent = ''; break;
  }
}

// --- Écouter le scroll sur les panneaux ---
function initScrollSyncListeners() {
  ['left', 'right'].forEach(id => {
    const wrap = document.getElementById('pane-' + id + '-scroll-wrap');
    if (wrap) {
      wrap.addEventListener('scroll', () => _syncScrollPane(id));
    }
  });
}

// --- Keyboard shortcuts ---
function _initSplitShortcuts() {
  document.addEventListener('keydown', (e) => {
    const ctrl = e.ctrlKey || e.metaKey;

    // Ctrl+\ → toggle split
    if (ctrl && e.key === '\\') {
      e.preventDefault();
      toggleSplit();
      return;
    }

    // Ctrl+Alt+← → focus left, Ctrl+Alt+→ → focus right
    if (ctrl && e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      e.preventDefault();
      const target = e.key === 'ArrowLeft' ? 'left' : 'right';
      if (target === 'right' && !_splitActive) return;
      setActivePane(target);
      return;
    }

    // Ctrl+W → fermer le panneau actif (si split ouvert)
    if (ctrl && e.key === 'w' && _splitActive) {
      e.preventDefault();
      const active = paneState.left.active ? 'left' : 'right';
      closePane(active);
      return;
    }

    // Ctrl+S → sauvegarder les 2 panneaux si split
    if (ctrl && e.key === 's') {
      if (_splitActive) {
        e.preventDefault();
        saveAllPanes();
        return;
      }
    }
  });
}

// --- Save all panes ---
async function saveAllPanes() {
  for (const id of ['left', 'right']) {
    const p = paneState[id];
    if (!p.path || !p.content) continue;
    const textarea = document.getElementById('pane-' + id + '-textarea');
    if (!textarea) continue;
    const content = textarea.value;
    _setPaneSaveIndicator(id, 'saving');
    try {
      const _api = window.REALIA_CONFIG?.API_BASE || window.API_BASE || 'http://localhost:8095';
    const r = await fetch(_api + '/api/save-file?path=' + encodeURIComponent(p.path), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content })
      });
      if (r.ok) {
        p.content = content;
        _setPaneSaveIndicator(id, 'saved');
      } else {
        _setPaneSaveIndicator(id, 'local');
      }
    } catch (e) {
      _setPaneSaveIndicator(id, 'local');
    }
  }
}

// --- Init ---
function initSplitView() {
  initSplitResizer();
  initScrollSyncListeners();
  _initSplitShortcuts();
  // Commencer en mode simple (gauche uniquement)
  _splitActive = false;
}

// Exporter
window.paneState = paneState;
window.toggleSplit = toggleSplit;
window.setActivePane = setActivePane;
window.openFileInPane = openFileInPane;
window.closePane = closePane;
window.toggleSyncScroll = toggleSyncScroll;
window.saveAllPanes = saveAllPanes;
window._setPaneSaveIndicator = _setPaneSaveIndicator;
window.initSplitView = initSplitView;
