// ============================================
// PANEL LAZY LOADER — Chargement différé des panneaux
// ============================================
// Panneaux lourds : 'youtu', 'logs', 'capacity'
// Panneaux légers : 'models', 'explorer', 'editor', 'chat'
// Politique : 1 seul panneau lourd actif à la fois
// ============================================

const panelRegistry = new Map();
const _HEAVY_PANELS = new Set(['youtu', 'logs', 'capacity']);
const _LIGHT_PANELS = new Set(['models', 'explorer', 'editor', 'chat']);
let _activeHeavyPanel = null;
const _MAX_ACTIVE_HEAVY = 1;

// Structure attendue dans le registre :
// { id, loaded: bool, loading: bool, domRef: element|null, data: any, heavy: bool, loader: fn }

function initPanelLoader(panelId, loaderFn, options = {}) {
  if (panelRegistry.has(panelId)) return;
  const heavy = options.heavy !== undefined ? options.heavy : _HEAVY_PANELS.has(panelId);
  panelRegistry.set(panelId, {
    id: panelId,
    loaded: false,
    loading: false,
    domRef: document.getElementById('panel-' + panelId),
    data: null,
    heavy,
    loader: loaderFn,
    unloader: options.unloader || null,
  });
  // Skeleton par défaut
  const el = panelRegistry.get(panelId).domRef;
  if (el && !el.dataset.lazyInit) {
    el.dataset.lazyInit = 'true';
    el.innerHTML = `<div class="loading-skeleton" style="padding:12px;color:#555;text-align:center;font-size:12px">⏳ Chargement ${panelId}...</div>`;
  }
}

async function loadPanel(panelId) {
  const entry = panelRegistry.get(panelId);
  if (!entry) return;
  if (entry.loaded) return; // déjà chargé
  if (entry.loading) return; // déjà en cours
  entry.loading = true;

  // Décharger l'ancien panneau lourd
  if (entry.heavy && _activeHeavyPanel && _activeHeavyPanel !== panelId) {
    await unloadPanel(_activeHeavyPanel);
  }

  const el = entry.domRef;
  if (el) el.innerHTML = `<div class="loading-skeleton" style="padding:12px;color:#888;text-align:center;font-size:12px"><span class="spinner"></span> Chargement ${panelId}...</div>`;

  try {
    const result = await entry.loader();
    entry.data = result;
    entry.loaded = true;
    entry.loading = false;
    if (entry.heavy) _activeHeavyPanel = panelId;
    // Badge "chargé" dans le header parent
    _setBadge(panelId, 'chargé', '#4caf50');
  } catch (err) {
    entry.loading = false;
    if (el) el.innerHTML = `<div style="padding:12px;color:#f44336;text-align:center;font-size:12px">❌ Erreur ${panelId} : ${err.message}<br><button onclick="retryLoadPanel('${panelId}')" style="margin-top:6px;background:#333;color:#ccc;border:1px solid #555;padding:4px 10px;border-radius:3px;cursor:pointer;font-size:11px">🔄 Réessayer</button></div>`;
    _setBadge(panelId, 'erreur', '#f44336');
  }
}

async function unloadPanel(panelId) {
  const entry = panelRegistry.get(panelId);
  if (!entry || !entry.loaded) return;
  // Appeler l'unloader si fourni
  if (entry.unloader) await entry.unloader(entry.data);
  entry.loaded = false;
  entry.data = null;
  if (entry.heavy && _activeHeavyPanel === panelId) _activeHeavyPanel = null;
  const el = entry.domRef;
  if (el) {
    // Remettre le skeleton
    el.innerHTML = `<div class="loading-skeleton" style="padding:12px;color:#555;text-align:center;font-size:12px">⏳ Chargement ${panelId}...</div>`;
  }
  _setBadge(panelId, 'en cache', '#888');
}

function retryLoadPanel(panelId) {
  const entry = panelRegistry.get(panelId);
  if (entry) { entry.loaded = false; loadPanel(panelId); }
}

function handleTabClick(tabElement, panelId) {
  tabElement.addEventListener('click', async (e) => {
    e.preventDefault();
    loadPanel(panelId);
  });
}

function _setBadge(panelId, text, color) {
  const header = document.querySelector(`[data-panel-header="${panelId}"] .panel-badge`);
  if (header) {
    header.textContent = text;
    header.style.color = color;
  }
}

// Remplacer les loaders d'intervalle pour les panneaux non chargés
function panelIsLoaded(panelId) {
  const entry = panelRegistry.get(panelId);
  return entry ? entry.loaded : false;
}

// ============================================
// Registre des panneaux de realia_dev_gui.html
// ============================================
// Appelé depuis l'init de la page
function initAllPanels() {
  // Panneaux légers (toujours dans le DOM, pas de lazy — déjà présents)
  _LIGHT_PANELS.forEach(id => {
    initPanelLoader(id, () => Promise.resolve(), { heavy: false });
    panelRegistry.get(id).loaded = true; // déjà dans le DOM initial
  });

  // Youtu-Agent (lourd)
  initPanelLoader('youtu', async () => {
    // Le contenu est déjà dans le HTML, on le marque juste chargé
    const el = document.getElementById('youtuPanel');
    if (el) el.style.display = 'block';
    return { loaded: true };
  }, { heavy: true, unloader: () => {
    // Arrêter le polling Youtu si actif
    if (window._youtuInterval) {
      clearInterval(window._youtuInterval);
      window._youtuInterval = null;
    }
    const el = document.getElementById('youtuPanel');
    if (el) el.style.display = 'none';
    return Promise.resolve();
  }});

  // Logs (lourd)
  initPanelLoader('logs', async () => {
    const logContent = document.getElementById('logContent');
    if (logContent) {
      logContent.innerHTML = '<div style="color:#888;padding:8px;text-align:center">⏳ Chargement...</div>';
      const _api = window.REALIA_CONFIG?.API_BASE || window.API_BASE || 'http://localhost:8095';
    const resp = await fetch(_api + '/api/logs');
      const data = await resp.json();
      const rawLogs = data.logs || '';
      STATE.logs = rawLogs;
      // Terminal rendering : colore les blocs execute_bash en vert néon
      logContent.innerHTML = _renderLogsAsTerminal(rawLogs);
    }
    return true;
  }, { heavy: true, unloader: () => {
    STATE.logs = '';
    return Promise.resolve();
  }});

  // Capacity (lourd — métriques système)
  initPanelLoader('capacity', async () => {
    const panel = document.getElementById('capacityPanel');
    if (panel) {
      panel.style.display = 'block';
      await updateCapacity();
    }
    return true;
  }, { heavy: true, unloader: () => {
    const panel = document.getElementById('capacityPanel');
    if (panel) panel.style.display = 'none';
    return Promise.resolve();
  }});
}

// Exporter pour usage global
// ── Rendu terminal : colore les blocs bash ├®x├®cut├®s ──
function _renderLogsAsTerminal(rawText) {
  if (!rawText) return '<div style="color:#555;padding:12px;text-align:center;font-size:12px">📭 Logs vides</div>';
  // ├ëchapper les balises HTML dangereuses
  let escaped = rawText
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  // Mettre en valeur les blocs SORTIE BASH (vert n├®on)
  escaped = escaped.replace(
    /\[SORTIE BASH\]([\s\S]*?)\[FIN SORTIE\]/g,
    '<div class="bash-block"><span class="bash-label">$ SORTIE BASH</span><pre class="bash-output">$1</pre></div>'
  );
  // Mettre en valeur les ├®tiquettes d'erreur (rouge)
  escaped = escaped.replace(
    /\[ERREUR (bash|agent)\]/g,
    '<span class="bash-error">[ERREUR $1]</span>'
  );
  // Retour ├á la ligne -> <br> pour pr├®server la mise en page
  escaped = escaped.replace(/\n/g, '<br>');
  return '<div class="terminal-output">' + escaped + '</div>';
}

window.initAllPanels = initAllPanels;
window.loadPanel = loadPanel;
window.unloadPanel = unloadPanel;
window.panelIsLoaded = panelIsLoaded;
window.panelRegistry = panelRegistry;
