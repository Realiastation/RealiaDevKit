// ============================================
// GIT PANEL — status, stage/unstage, commit, badges
// ============================================

const GIT_API = (window.REALIA_CONFIG?.API_BASE || 'http://localhost:8095') + '/api/git';


let _gitStatusRefreshTimer = null;
let _gitBadgeMap = {}; // path → status char

// ── Load Git Status ──────────────────────────

async function loadGitStatus() {
  // Vérifier si c'est un repo
  let isRepo = false;
  try {
    const ir = await fetch(`${GIT_API}/is-repo`);
    const ird = await ir.json();
    isRepo = ird.is_repo;
  } catch(e) { /* offline */ }

  const panel = document.getElementById('panel-git-content');
  if (!panel) return;

  if (!isRepo) {
    panel.innerHTML = `<div style="padding:12px;color:#888;font-size:12px;text-align:center">
      Aucun dépôt Git.<br><button onclick="initGitRepo()" style="margin-top:8px;background:#00bcd4;color:#111;border:none;padding:4px 12px;border-radius:4px;cursor:pointer">Initialiser .git</button>
    </div>`;
    return;
  }

  try {
    const r = await fetch(`${GIT_API}/status`);
    const d = await r.json();
    _renderGitPanel(panel, d);
    _updateBadges(d.files);
  } catch(e) {
    panel.innerHTML = `<div style="color:#f44336;padding:8px;font-size:11px">Erreur: ${e.message}</div>`;
  }
}

// ── Render Git Panel ─────────────────────────

function _renderGitPanel(panel, data) {
  const { branch, files, ahead, behind, dirty } = data;
  const modified = files.filter(f => !f.staged && (f.status === 'M' || f.status === 'U' || f.status === 'D'));
  const staged = files.filter(f => f.staged);

  let html = `<div class="git-header">
    <span class="git-branch">${escapeHtml(branch)}</span>
    ${ahead ? `<span class="git-ahead">↑${ahead}</span>` : ''}
    ${behind ? `<span class="git-behind">↓${behind}</span>` : ''}
    ${dirty ? '<span class="git-dirty">⚡ modifié</span>' : '<span class="git-clean">✅ propre</span>'}
    <button onclick="loadGitStatus()" class="git-refresh-btn" title="Rafraîchir">🔄</button>
  </div>`;

  // Modifications
  html += `<div class="git-section"><div class="git-section-title">Modifications (${modified.length})</div>`;
  if (modified.length === 0) {
    html += `<div class="git-empty">Aucune modification</div>`;
  } else {
    for (const f of modified) {
      const label = _statusLabel(f.status);
      const cls = _statusClass(f.status);
      html += `<div class="git-file" data-path="${escapeHtml(f.path)}">
        <span class="git-badge ${cls}">${label}</span>
        <span class="git-path">${escapeHtml(f.path)}</span>
        <button class="git-btn git-stage-btn" onclick="stageFile('${escapeHtml(f.path).replace(/'/g,"\\'")}')">+</button>
        <button class="git-btn git-diff-btn" onclick="openDiffViewer('${escapeHtml(f.path).replace(/'/g,"\\'")}')">📄</button>
      </div>`;
    }
  }
  html += `</div>`;

  // Staged
  html += `<div class="git-section"><div class="git-section-title">Index (${staged.length})</div>`;
  if (staged.length === 0) {
    html += `<div class="git-empty">Rien dans l'index</div>`;
  } else {
    for (const f of staged) {
      const label = _statusLabel(f.status);
      const cls = _statusClass(f.status);
      html += `<div class="git-file" data-path="${escapeHtml(f.path)}">
        <span class="git-badge ${cls}">${label}</span>
        <span class="git-path">${escapeHtml(f.path)}</span>
        <button class="git-btn git-unstage-btn" onclick="unstageFile('${escapeHtml(f.path).replace(/'/g,"\\'")}')">−</button>
      </div>`;
    }
  }
  html += `</div>`;

  // Commit
  html += `<div class="git-commit-area">
    <input id="gitCommitMsg" placeholder="Message de commit..." class="git-commit-input" ${staged.length === 0 ? 'disabled' : ''} />
    <button class="git-btn git-commit-btn" onclick="gitCommit()" ${staged.length === 0 ? 'disabled' : ''}>✅ Commit</button>
  </div>`;

  panel.innerHTML = html;
}

// ── Badges in Explorer ───────────────────────

function _updateBadges(files) {
  _gitBadgeMap = {};
  for (const f of files) {
    _gitBadgeMap[f.path] = f.status;
  }
  _applyBadges();
}

function _applyBadges() {
  document.querySelectorAll('#file-list li[data-path]').forEach(li => {
    const path = li.dataset.path;
    const status = _gitBadgeMap[path];
    const existing = li.querySelector('.git-file-badge');
    if (existing) existing.remove();

    if (status) {
      const badge = document.createElement('span');
      badge.className = `git-file-badge ${_statusClass(status)}`;
      badge.textContent = _statusLabel(status);
      badge.style.cssText = 'float:right;font-size:10px;padding:0 5px;border-radius:3px;margin-right:4px';
      badge.style.fontSize = '9px';
      li.appendChild(badge);
    }
  });
}

// ── Actions ──────────────────────────────────

async function stageFile(path) {
  await fetch(`${GIT_API}/stage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths: [path] })
  });
  loadGitStatus();
}

async function unstageFile(path) {
  await fetch(`${GIT_API}/unstage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths: [path] })
  });
  loadGitStatus();
}

async function gitCommit() {
  const input = document.getElementById('gitCommitMsg');
  if (!input || !input.value.trim()) return;
  try {
    const r = await fetch(`${GIT_API}/commit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: input.value.trim() })
    });
    const d = await r.json();
    if (r.ok) {
      _showGitToast(`✅ Commit: ${d.message}`);
      input.value = '';
    } else {
      _showGitToast(`❌ ${d.detail || 'Erreur'}`);
    }
  } catch(e) {
    _showGitToast(`❌ ${e.message}`);
  }
  loadGitStatus();
}

async function initGitRepo() {
  try {
    const r = await fetch(`${GIT_API}/init`, { method: 'POST' });
    if (r.ok) {
      _showGitToast('✅ Dépôt Git initialisé');
      loadGitStatus();
    } else {
      const d = await r.json();
      _showGitToast(`❌ ${d.detail || 'Erreur'}`);
    }
  } catch(e) {
    _showGitToast(`❌ ${e.message}`);
  }
}

// ── Helpers ──────────────────────────────────

function _statusLabel(status) {
  return { M: 'M', U: '?', D: 'D', A: 'A', R: 'R' }[status] || ' ';
}

function _statusClass(status) {
  return { M: 'badge-modified', U: 'badge-untracked', D: 'badge-deleted', A: 'badge-added', R: 'badge-renamed' }[status] || '';
}

function _showGitToast(msg) {
  const t = document.createElement('div');
  t.textContent = msg;
  t.style.cssText = 'position:fixed;bottom:50px;left:50%;transform:translateX(-50%);background:#333;color:#eee;padding:6px 14px;border-radius:5px;font-size:12px;z-index:9001;box-shadow:0 4px 12px rgba(0,0,0,.5);opacity:0;transition:opacity .2s';
  document.body.appendChild(t);
  requestAnimationFrame(() => t.style.opacity = '1');
  setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 200); }, 2000);
}

function escapeHtml(t) {
  return t.replace(/&/g,'&').replace(/</g,'<').replace(/>/g,'>').replace(/"/g,'"');
}

// ── Auto-refresh & Init ──────────────────────

function startGitAutoRefresh() {
  loadGitStatus();
  if (_gitStatusRefreshTimer) clearInterval(_gitStatusRefreshTimer);
  _gitStatusRefreshTimer = setInterval(loadGitStatus, 30000);
}

function stopGitAutoRefresh() {
  if (_gitStatusRefreshTimer) {
    clearInterval(_gitStatusRefreshTimer);
    _gitStatusRefreshTimer = null;
  }
}

// Export
window.loadGitStatus = loadGitStatus;
window.stageFile = stageFile;
window.unstageFile = unstageFile;
window.gitCommit = gitCommit;
window.initGitRepo = initGitRepo;
window.startGitAutoRefresh = startGitAutoRefresh;
window.stopGitAutoRefresh = stopGitAutoRefresh;

// Auto-init
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startGitAutoRefresh);
} else {
  startGitAutoRefresh();
}
// v2
