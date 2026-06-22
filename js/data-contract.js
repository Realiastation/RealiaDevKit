/**
 * data-contract.js — Contrat JSON unique entre Backend (Python) et Frontend (UI Web).
 *
 * Toute réponse passant du backend au frontend DOIT être validée par
 * `validateUIContract()` avant d'être consommée. Si une clé manque ou
 * est invalide, l'UI affiche une erreur propre en console au lieu de
 * figer l'écran ou de casser l'affichage.
 *
 * Structure du contrat (générée côté Python par format_ui_payload()) :
 * {
 *   "ui_metadata": { "theme": "realia-cyberpunk", "version": "3.0" },
 *   "agent":       { "name": "...", "status": "idle|busy|error" },
 *   "content":     { "text": "...", "timestamp": "ISO-8601" },
 *   "system":      { "slot_active": true, "metrics": {} }
 * }
 *
 * Usage :
 *   import { validateUIContract, safeGet } from './js/data-contract.js';
 *   const safe = validateUIContract(rawData);
 *   console.log(safe.agent.name);  // toujours défini
 *   console.log(safeGet(safe, 'content.text', '(vide)'));  // fallback chaîné
 */

const UI_CONTRACT_DEFAULTS = {
  ui_metadata: { theme: 'realia-cyberpunk', version: '3.0' },
  agent:       { name: 'inconnu', status: 'error' },
  content:     { text: '', timestamp: new Date().toISOString() },
  system:      { slot_active: false, metrics: {} },
};

/**
 * Valide une donnée entrante contre le contrat UI.
 * Retourne TOUJOURS un objet conforme, jamais null/undefined.
 * Log une erreur en console pour chaque clé manquante.
 *
 * @param {any} data - Donnée brute (souvent du JSON.parse ou fetch)
 * @returns {object} Donnée sécurisée avec toutes les clés du contrat
 */
function validateUIContract(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    console.warn('[DataContract] ⚠️ Donnée invalide reçue (null/array/primitive). Utilisation du défaut.');
    return { ...UI_CONTRACT_DEFAULTS, content: { ...UI_CONTRACT_DEFAULTS.content, timestamp: new Date().toISOString() } };
  }

  const safe = {};

  // ui_metadata
  safe.ui_metadata = _safeObj(data.ui_metadata, UI_CONTRACT_DEFAULTS.ui_metadata);
  if (!data.ui_metadata) {
    console.warn('[DataContract] ⚠️ Clé manquante: ui_metadata');
  }

  // agent
  safe.agent = _safeObj(data.agent, UI_CONTRACT_DEFAULTS.agent);
  if (!data.agent) {
    console.warn('[DataContract] ⚠️ Clé manquante: agent');
  } else {
    if (!data.agent.name)  console.warn('[DataContract] ⚠️ Clé manquante: agent.name');
    if (!data.agent.status) console.warn('[DataContract] ⚠️ Clé manquante: agent.status');
  }

  // content
  safe.content = _safeObj(data.content, UI_CONTRACT_DEFAULTS.content);
  if (!data.content) {
    console.warn('[DataContract] ⚠️ Clé manquante: content');
  } else {
    if (!data.content.text)      console.warn('[DataContract] ⚠️ Clé manquante: content.text');
    if (!data.content.timestamp) console.warn('[DataContract] ⚠️ Clé manquante: content.timestamp');
  }

  // system
  safe.system = _safeObj(data.system, UI_CONTRACT_DEFAULTS.system);
  if (!data.system) {
    console.warn('[DataContract] ⚠️ Clé manquante: system');
  } else {
    safe.system.slot_active = typeof data.system.slot_active === 'boolean' ? data.system.slot_active : false;
    safe.system.metrics = (data.system.metrics && typeof data.system.metrics === 'object' && !Array.isArray(data.system.metrics))
      ? data.system.metrics : {};
  }

  return safe;
}

/**
 * Accède en sécurité à une propriété imbriquée (ex: "content.text").
 * Si la propriété n'existe pas, retourne fallback.
 *
 * @param {object} obj - Objet validé par validateUIContract
 * @param {string} path - Chemin pointé (ex: "system.metrics.vram")
 * @param {*} fallback - Valeur par défaut si absente
 * @returns {*} Valeur ou fallback
 */
function safeGet(obj, path, fallback = null) {
  if (!obj || typeof obj !== 'object') return fallback;
  const keys = path.split('.');
  let current = obj;
  for (const key of keys) {
    if (current === null || current === undefined || typeof current !== 'object') {
      return fallback;
    }
    if (!(key in current)) return fallback;
    current = current[key];
  }
  return current !== undefined ? current : fallback;
}

/**
 * Fusion sécurisée : si la source est un objet valide, on fusionne
 * avec les défauts comblés. Sinon, on retourne une copie des défauts.
 * @private
 */
function _safeObj(src, defaults) {
  if (!src || typeof src !== 'object' || Array.isArray(src)) {
    return { ...defaults };
  }
  return { ...defaults, ...src };
}

// Exporter dans le scope global (Vanilla JS, pas de module loader)
window.validateUIContract = validateUIContract;
window.safeGet = safeGet;
window.UI_CONTRACT_DEFAULTS = UI_CONTRACT_DEFAULTS;

console.log('[DataContract] ✅ Contrat chargé. Toute réponse UI sera validée.');
