// ============================================
// FOCUS MODE — Zen layout avec sauvegarde / restore
// ============================================

let _focusActive = false;
let _focusLayoutBackup = null;
let _focusToastTimer = null;
const LS_FOCUS_KEY = 'realia_focus_layout_backup';

function toggleFocusMode() {
  if (_focusActive) {
    _exitFocusMode();
  } else {
    _enterFocusMode();
  }
}

function _enterFocusMode() {
  if (_focusActive) return;
  _focusActive = true;

  // Sauvegarder l'état de visibilité de tous les panneaux
  const panels = document.querySelectorAll('#panels > .panel, #models-panel, #explorer, #editor, #chat');
  _focusLayoutBackup = {};
  panels.forEach(p => {
    const id = p.id || p.className;
    _focusLayoutBackup[id] = {
      collapsed: p.classList.contains('collapsed'),
      hidden: p.classList.contains('hidden'),
      width: p.style.width,
      flex: p.style.flex
    };
  });

  // Sauvegarder aussi la toolbar secondaire et menuBar (les masquer optionnellement)
  const toolbar = document.getElementById('toolbar');
  if (toolbar) {
    _focusLayoutBackup._toolbarHidden = toolbar.classList.contains('hidden');
    toolbar.classList.add('hidden');
  }

  // Masquer models, explorer, chat — garder seulement l'éditeur
  document.getElementById('models-panel')?.classList.add('collapsed', 'focus-hidden');
  document.getElementById('explorer')?.classList.add('hidden', 'focus-hidden');
  document.getElementById('chat')?.classList.add('hidden', 'focus-hidden');

  // Persistance
  try {
    localStorage.setItem(LS_FOCUS_KEY, JSON.stringify(_focusLayoutBackup));
  } catch(e) {}

  // Toast
  _showFocusToast('Mode Focus activé • Ctrl+Shift+F pour quitter');

  // Sauvegarder et enregistrer la commande palette pour le retour
  _focusActive = true;
}

function _exitFocusMode() {
  if (!_focusActive) return;
  _focusActive = false;

  // Restaurer les panneaux depuis le backup
  if (_focusLayoutBackup) {
    Object.keys(_focusLayoutBackup).forEach(key => {
      const el = document.getElementById(key);
      if (!el) return;
      const state = _focusLayoutBackup[key];
      if (state.collapsed) el.classList.add('collapsed');
      else el.classList.remove('collapsed');
      if (state.hidden) el.classList.add('hidden');
      else el.classList.remove('hidden');
      if (state.width) el.style.width = state.width;
      if (state.flex) el.style.flex = state.flex;
    });
    // Restaurer toolbar
    const toolbar = document.getElementById('toolbar');
    if (toolbar && !_focusLayoutBackup._toolbarHidden) {
      toolbar.classList.remove('hidden');
    }
  }

  // Nettoyer les classes focus-hidden
  document.querySelectorAll('.focus-hidden').forEach(el => el.classList.remove('focus-hidden'));

  // Nettoyer localStorage
  try { localStorage.removeItem(LS_FOCUS_KEY); } catch(e) {}

  _focusLayoutBackup = null;

  // Restaurer le focus sur l'éditeur
  const ta = document.querySelector('.editor-pane.focused .pane-textarea');
  if (ta) setTimeout(() => ta.focus(), 50);
  else {
    const input = document.getElementById('chatInput');
    if (input) input.focus();
  }

  _showFocusToast('Mode Focus désactivé');
}

function _showFocusToast(msg) {
  const existing = document.getElementById('focusToast');
  if (existing) existing.remove();
  if (_focusToastTimer) clearTimeout(_focusToastTimer);

  const toast = document.createElement('div');
  toast.id = 'focusToast';
  toast.textContent = msg;
  toast.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#00bcd4;color:#111;padding:8px 16px;border-radius:6px;font-size:13px;font-family:inherit;z-index:9000;box-shadow:0 4px 12px rgba(0,0,0,.5);transition:opacity .3s;opacity:1';
  document.body.appendChild(toast);

  _focusToastTimer = setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => { if (toast.parentNode) toast.remove(); }, 300);
  }, 2500);
}

// Enregistrer dans la command palette
if (typeof registerCommand === 'function') {
  registerCommand({ id: 'focus.mode.zen', label: 'Mode Focus (Zen)', shortcut: 'Ctrl+Shift+F', icon: '⛶', action: toggleFocusMode });
}

// Raccourci Ctrl+Shift+F
document.addEventListener('keydown', (e) => {
  const ctrl = e.ctrlKey || e.metaKey;
  if (ctrl && e.shiftKey && (e.key === 'f' || e.key === 'F')) {
    e.preventDefault();
    toggleFocusMode();
  }
});

// Exporter
window.toggleFocusMode = toggleFocusMode;
window._focusActive = _focusActive;
