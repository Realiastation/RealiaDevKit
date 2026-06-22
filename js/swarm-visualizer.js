// js/swarm-visualizer.js
// Visualiseur Swarm 2.0 - Module isolé, non-intrusif
(function() {
'use strict';

// État local du visualiseur
const swarmState = {
  currentActor: 'Q3.6',
  lastSwap: null,
  activeTools: [],
  taskHistory: [],
  previousHistory: []
};

// Configuration
const CONFIG = {
  pollInterval: 2000, // 2s
  maxHistoryItems: 10,
  apiBase: window.API_BASE || 'http://localhost:8095'
};

// Cache des éléments DOM
let visualizerContainer = null;

// Initialisation
function init() {
  // Attendre que le DOM soit prêt
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
    return;
  }

  // Créer le conteneur s'il n'existe pas
  visualizerContainer = document.getElementById('swarm-visualizer');
  if (!visualizerContainer) {
    console.warn('[SwarmViz] Container #swarm-visualizer not found');
    return;
  }

  // Appliquer les styles de base
  visualizerContainer.style.cssText = `
    position: relative;
    width: 100%;
    max-height: 150px;
    margin-bottom: 10px; border-radius: 4px;
    background: rgba(25, 25, 28, 0.95);
    border: 1px solid #3a3a3c;
    border-radius: 8px;
    padding: 12px;
    font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
    font-size: 12px;
    color: #e0e0e0;
    overflow-y: auto;
    z-index: 10;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
    backdrop-filter: blur(8px);
  `;
  renderUI();
  
  // Injection en header du chat panel
  const chatPanel = document.getElementById('chatMessages')?.parentElement;
  if (chatPanel) {
    chatPanel.insertBefore(visualizerContainer, chatPanel.firstChild);
    console.log('[SwarmViz] Intégré en header du chat panel');
  } else {
    document.body.insertBefore(visualizerContainer, document.body.firstChild);
  }
  startPolling();
  console.log('[SwarmViz] Initialized');
}

// Rendu de l'UI
function renderUI() {
  visualizerContainer.innerHTML = `
    <div style="display: flex; justify-content: space-between; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid #555;">
      <strong style="color: #4fc3f7;">🧠 Swarm Monitor</strong>
      <span id="swarm-model" style="color: #81c784;">${swarmState.currentActor}</span>
      <span id="swarm-swap-indicator" style="font-size: 10px; color: #888;"></span>
    </div>
    <div id="swarm-events" style="max-height: 300px; overflow-y: auto;"></div>
  `;
}

// Ajout d'un événement
function addEvent(type, data) {
  const eventsContainer = document.getElementById('swarm-events');
  if (!eventsContainer) return;

  const eventEl = document.createElement('div');
  eventEl.style.cssText = `
    margin: 6px 0;
    padding: 6px;
    background: rgba(255,255,255,0.05);
    border-left: 3px solid ${type === 'swap' ? '#ffb74d' : '#4fc3f7'};
    border-radius: 4px;
    animation: slideIn 0.3s ease-out;
  `;

  const timestamp = new Date().toLocaleTimeString('fr-FR', { hour12: false });

  if (type === 'swap') {
    eventEl.innerHTML = `
      <div style="display: flex; justify-content: space-between;">
        <span style="color: #ffb74d;">🔄 Swap</span>
        <span style="color: #888; font-size: 10px;">${timestamp}</span>
      </div>
      <div style="margin-top: 4px; color: #ccc;">
        ${data.from} → ${data.to}
      </div>
    `;
    swarmState.currentActor = data.to;
    const modelEl = document.getElementById('swarm-model');
    if (modelEl) modelEl.textContent = data.to;
  } else if (type === 'tool') {
    eventEl.innerHTML = `
      <div style="display: flex; justify-content: space-between;">
        <span style="color: #4fc3f7;">🔧 ${data.tool}</span>
        <span style="color: #888; font-size: 10px;">${timestamp}</span>
      </div>
      <div style="margin-top: 4px; color: #aaa; font-size: 11px;">
        ${data.status === 'executing' ? '⏳' : '✅'} ${data.file || ''}
      </div>
    `;
  }

  eventsContainer.insertBefore(eventEl, eventsContainer.firstChild);

  // Limiter l'historique
  while (eventsContainer.children.length > CONFIG.maxHistoryItems) {
    eventsContainer.removeChild(eventsContainer.lastChild);
  }
}

// Polling pour récupérer l'état du Contrat-Travail (endpoint unique)
async function pollSwarmEvents() {
  try {
    const res = await fetch(CONFIG.apiBase + '/contract/status');
    if (!res.ok) {
      console.warn('[SwarmViz] ⚠️ /contract/status a retourné', res.status, 
        '- Backend peut-être en cours de swap ou indisponible');
      return;
    }

    const contrat = await res.json();

    // Vérifier la structure minimale du contrat
    if (!contrat || !contrat.workflow || !contrat.status) {
      console.warn('[SwarmViz] ⚠️ Structure contrat invalide:', contrat);
      return;
    }

    const currentActor = contrat.workflow.current_actor || 'Q3.6';
    const nextActor = contrat.workflow.next_actor_requested || null;
    const contratStatus = contrat.status;
    const history = contrat.history || [];

    // ── Mettre à jour le statut du projet ──
    const modelEl = document.getElementById('swarm-model');
    if (modelEl) {
      const statusEmoji = {
        'INIT': '🆕', 'PLANNING': '📋', 'CODING': '💻',
        'REVIEW': '🔍', 'DONE': '✅', 'FAILED': '❌', 'IDLE': '⏸️'
      }[contratStatus] || '🔄';
      let label = `${currentActor}`;
      if (nextActor && nextActor !== 'DONE') {
        label += ` → ${nextActor}`;
      }
      modelEl.textContent = `${statusEmoji} ${label}`;

      // ── Animation agent-actif ──
      // Applique la classe .agent-active à l'élément du modèle courant
      modelEl.classList.add('agent-active');
    }

    // ── Indicateur de swap / cache actif ──
    const swapIndicator = document.getElementById('swarm-swap-indicator');
    if (swapIndicator) {
      if (contratStatus === 'INIT' || contratStatus === 'IDLE') {
        swapIndicator.textContent = '⏸️ En attente';
        swapIndicator.style.color = '#888';
      } else if (contratStatus === 'FAILED') {
        swapIndicator.textContent = '❌ Échec';
        swapIndicator.style.color = '#f44336';
      } else if (swarmState.currentActor !== currentActor) {
        // Swap en cours détecté
        swapIndicator.textContent = '🔄 Swap en cours / Cache RAM actif';
        swapIndicator.style.color = '#ffb74d';
      } else {
        swapIndicator.textContent = '✅ Cache RAM actif';
        swapIndicator.style.color = '#4caf50';
      }
    }

    // ── Détection de swap (changement d'acteur courant) ──
    if (currentActor !== swarmState.currentActor) {
      addEvent('swap', {
        from: swarmState.currentActor,
        to: currentActor
      });
      swarmState.currentActor = currentActor;
    }

    // ── Détection de nouveaux événements dans l'historique ──
    if (history.length > swarmState.previousHistory.length) {
      // Nouvelles entrées détectées (en début ou fin de tableau)
      const newEntries = history.slice(swarmState.previousHistory.length - history.length);
      for (const entry of newEntries) {
        // Ajouter comme événement 'tool' si pas déjà un swap
        if (!entry.includes('Contrat mis à jour') && !entry.includes('Début')) {
          addEvent('tool', {
            tool: 'contrat',
            status: 'completed',
            file: entry.substring(0, 80)
          });
        }
      }
      swarmState.previousHistory = [...history];
    }

    // Si l'historique a été réinitialisé, mettre à jour la référence
    if (history.length < swarmState.previousHistory.length) {
      swarmState.previousHistory = [...history];
    }

  } catch (error) {
    console.warn('[SwarmViz] ⚠️ /contract/status injoignable :', 
      error.message || error,
      '- Vérifie que le backend DevKit tourne sur le port 8095');
  }
}

// Démarrer le polling
function startPolling() {
  setInterval(pollSwarmEvents, CONFIG.pollInterval);
}

// Styles CSS additionnels (injectés dynamiquement)
function injectStyles() {
  const style = document.createElement('style');
  style.textContent = `
    @keyframes slideIn {
      from {
        opacity: 0;
        transform: translateX(20px);
      }
      to {
        opacity: 1;
        transform: translateX(0);
      }
    }
    @keyframes pulseAgent {
      0%, 100% {
        box-shadow: 0 0 5px #8b5cf6, 0 0 10px #8b5cf6;
      }
      50% {
        box-shadow: 0 0 15px #8b5cf6, 0 0 30px #06b6d4;
      }
    }
    .agent-active {
      animation: pulseAgent 2s ease-in-out infinite;
      border-radius: 4px;
      padding: 2px 8px;
      background: rgba(139,92,246,0.15);
      color: #c084fc !important;
    }
    #swarm-visualizer::-webkit-scrollbar {
      width: 6px;
    }
    #swarm-visualizer::-webkit-scrollbar-track {
      background: rgba(0,0,0,0.2);
    }
    #swarm-visualizer::-webkit-scrollbar-thumb {
      background: #555;
      border-radius: 3px;
    }
  `;
  document.head.appendChild(style);
}

// Démarrage
injectStyles();
init();

// Exposer API publique (optionnel, pour debug)
window.SwarmVisualizer = {
  state: swarmState,
  addEvent: addEvent
};

})();
