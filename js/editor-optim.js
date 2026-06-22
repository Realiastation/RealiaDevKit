// ============================================
// EDITOR OPTIM — Debounce + Autosave + Crash Recovery
// ============================================
// Sauvegarde locale immédiate (localStorage), push API différé (1.5s)
// Backup de session pour récupération de crash
// Indicateurs visuels : 🟢 🟡 🔵
// ============================================

const AUTOSAVE_DELAY = 1500; // ms avant push API
const LS_PREFIX = 'realia_backup_';
let _autosaveTimer = null;
let _lastSavedContent = {};
let _saveStatus = 'idle'; // 'idle' | 'saving' | 'saved' | 'local'

// Map paneId → { filePath, lastSaved, status }
let _paneStates = { left: { status: 'idle' }, right: { status: 'idle' } };

// --- Debounce universel ---
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => { clearTimeout(timeout); func(...args); };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// --- Indicateur visuel ---
function _setSaveIndicator(status) {
  const el = document.getElementById('saveIndicator');
  if (!el) return;
  _saveStatus = status;
  switch (status) {
    case 'saved': el.textContent = '🟢 Sauvegardé'; el.style.color = '#4caf50'; break;
    case 'saving': el.textContent = '🟡 Sauvegarde...'; el.style.color = '#ff9800'; break;
    case 'local': el.textContent = '🔵 Brouillon local'; el.style.color = '#42a5f5'; break;
    default: el.textContent = ''; break;
  }
}

// --- Sauvegarde locale immédiate (localStorage) ---
function saveLocalBackup(filePath, content) {
  if (!filePath) return;
  try {
    const key = LS_PREFIX + filePath.replace(/[^a-zA-Z0-9_\-\.\/]/g, '_');
    localStorage.setItem(key, JSON.stringify({ content, savedAt: Date.now(), path: filePath }));
  } catch (e) {
    // localStorage plein ou désactivé → silencieux
  }
}

// --- Load backup ---
function loadLocalBackup(filePath) {
  try {
    const key = LS_PREFIX + filePath.replace(/[^a-zA-Z0-9_\-\.\/]/g, '_');
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (data.path !== filePath) return null;
    return data;
  } catch (e) {
    return null;
  }
}

// --- Effacer backup après succès API ---
function clearLocalBackup(filePath) {
  try {
    const key = LS_PREFIX + filePath.replace(/[^a-zA-Z0-9_\-\.\/]/g, '_');
    localStorage.removeItem(key);
  } catch (e) {}
}

// --- Vérifier si un fichier a changé sur le serveur ---
async function checkServerConflict(filePath, localContent) {
  try {
    const _api = window.REALIA_CONFIG?.API_BASE || window.API_BASE || 'http://localhost:8095';
    const r = await fetch(_api + '/api/file?path=' + encodeURIComponent(filePath));
    if (!r.ok) return false;
    const d = await r.json();
    const serverContent = d.content || '';
    if (serverContent === localContent) return false;
    // Comparer hash rapide
    const hashLocal = _simpleHash(localContent);
    const hashServer = _simpleHash(serverContent);
    return hashLocal !== hashServer;
  } catch (e) {
    return false;
  }
}

function _simpleHash(s) {
  let hash = 0;
  for (let i = 0; i < Math.min(s.length, 2000); i++) {
    const chr = s.charCodeAt(i);
    hash = ((hash << 5) - hash) + chr;
    hash |= 0;
  }
  return hash;
}

// --- Push API (debounced) ---
const debouncedApiSave = debounce(async function(filePath, content) {
  if (!filePath) return;
  _setSaveIndicator('saving');
  try {
    const _api = window.REALIA_CONFIG?.API_BASE || window.API_BASE || 'http://localhost:8095';
    const r = await fetch(_api + '/api/save-file?path=' + encodeURIComponent(filePath), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content })
    });
    if (r.ok) {
      _lastSavedContent = content;
      _setSaveIndicator('saved');
      clearLocalBackup(filePath);
    } else {
      _setSaveIndicator('local');
    }
  } catch (e) {
    _setSaveIndicator('local'); // réseau HS → backup local conservé
  }
}, AUTOSAVE_DELAY);

// --- Fonction principale appelée à chaque input ---
function onEditorInput(filePath, content) {
  if (!filePath) return;
  // Backup local immédiat
  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(() => saveLocalBackup(filePath, content), { timeout: 300 });
  } else {
    saveLocalBackup(filePath, content);
  }
  // Push API différé
  debouncedApiSave(filePath, content);
}

// --- Récupération de crash ---
function checkCrashRecovery(filePath) {
  return new Promise((resolve) => {
    const backup = loadLocalBackup(filePath);
    if (!backup) return resolve(null);
    if (backup.content === _lastSavedContent) return resolve(null); // déjà sauvegardé

    // Vérifier si le serveur a une version plus récente
    checkServerConflict(filePath, backup.content).then(hasConflict => {
      resolve({ backup, hasConflict });
    });
  });
}

// --- Beforeunload : forcer backup local synchrone ---
window.addEventListener('beforeunload', () => {
  const path = window.STATE?.currentPath;
  const content = window.STATE?.currentContent;
  if (path && content) {
    saveLocalBackup(path, content);
  }
});

// --- Modale de récupération ---
function showRecoveryModal(backup, filePath) {
  const overlay = document.createElement('div');
  overlay.id = 'recoveryOverlay';
  overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.75);z-index:10000;display:flex;align-items:center;justify-content:center';
  const time = new Date(backup.savedAt).toLocaleString('fr-FR');
  overlay.innerHTML = `
    <div style="background:#1a1a2e;border:1px solid #555;border-radius:8px;padding:24px;max-width:480px;width:90%;box-shadow:0 8px 24px rgba(0,0,0,.6)">
      <div style="font-size:18px;margin-bottom:8px">♻️ Version non sauvegardée trouvée</div>
      <div style="color:#aaa;font-size:13px;margin-bottom:12px">
        Une version locale datant du <strong>${time}</strong> a été retrouvée pour <code style="background:#222;padding:2px 6px;border-radius:3px">${filePath}</code>.<br>
        Que souhaitez-vous faire ?
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button onclick="document.getElementById('recoveryOverlay').remove();window._rejectRecovery && window._rejectRecovery()" style="background:#333;color:#ccc;border:1px solid #555;padding:8px 16px;border-radius:4px;cursor:pointer;font-family:inherit">Abandonner</button>
        <button onclick="document.getElementById('recoveryOverlay').remove();window._acceptRecovery && window._acceptRecovery()" style="background:#00bcd4;color:#111;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;font-family:inherit;font-weight:600">♻️ Récupérer</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
}

// --- Récupérer le dernier backup au chargement d'un fichier ---
async function tryRecover(filePath) {
  const result = await checkCrashRecovery(filePath);
  if (!result || !result.backup) return false;

  return new Promise((resolve) => {
    window._acceptRecovery = () => {
      clearLocalBackup(filePath);
      resolve(result.backup.content);
    };
    window._rejectRecovery = () => {
      clearLocalBackup(filePath);
      resolve(null);
    };
    showRecoveryModal(result.backup, filePath);
  });
}

// Exporter
window.debounce = debounce;
window.onEditorInput = onEditorInput;
window._setSaveIndicator = _setSaveIndicator;
window.tryRecover = tryRecover;
window._lastSavedContent = _lastSavedContent;
window.checkServerConflict = checkServerConflict;
