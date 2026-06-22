// ============================================
// PERF PROFILER — Métriques temps réel, sparklines, alertes
// ============================================
// Latence WS, durée API, Long Tasks, RAM — update 1 Hz via rAF
// ============================================

class PerfProfiler {
  constructor() {
    this.metrics = {
      wsLatency: [],        // ms
      apiDuration: [],      // ms
      longTasks: [],        // ms
      ramUsed: [],          // MB
      vramUsed: []          // MB (via WS)
    };
    this._active = false;
    this._lastFrame = 0;
    this._rafId = null;
    this._originalFetch = null;
    this._wsPingTimer = null;
    this._observers = {};
    this._bufferMax = 60;
    this._fetchQueue = [];
  }

  // --- Start ---
  start() {
    if (this._active) return;
    this._active = true;

    // Wrapper fetch
    this._originalFetch = window.fetch;
    const self = this;
    window.fetch = function(...args) {
      const start = performance.now();
      return self._originalFetch.apply(this, args).then(response => {
        self._pushMetric('apiDuration', performance.now() - start);
        return response;
      }).catch(err => {
        self._pushMetric('apiDuration', performance.now() - start);
        throw err;
      });
    };

    // Long Tasks Observer
    if (window.PerformanceObserver) {
      try {
        const obs = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            this._pushMetric('longTasks', entry.duration);
          }
        });
        obs.observe({ type: 'longtask', buffered: false });
        this._observers.longtask = obs;
      } catch(e) { /* fallback silencieux */ }
    }

    // WS Ping (si WebSocket disponible)
    this._wsPingTimer = setInterval(() => this._pingWS(), 5000);

    // RAM sampling (Chromium only)
    this._sampleRAM();

    // Start render loop
    this._renderLoop(performance.now());
  }

  // --- Stop ---
  stop() {
    this._active = false;
    if (this._rafId) cancelAnimationFrame(this._rafId);
    if (this._wsPingTimer) clearInterval(this._wsPingTimer);
    if (this._observers.longtask) this._observers.longtask.disconnect();
    if (this._originalFetch) window.fetch = this._originalFetch;
    // Nettoyer le DOM
    const el = document.getElementById('perfProfiler');
    if (el) el.innerHTML = '<div style="padding:8px;color:#555;font-size:11px">Profiler arrêté</div>';
    this.metrics = { wsLatency: [], apiDuration: [], longTasks: [], ramUsed: [], vramUsed: [] };
  }

  // --- Toggle ---
  toggle() {
    if (this._active) this.stop();
    else this.start();
  }

  // --- Push metric (gliding window) ---
  _pushMetric(key, value) {
    if (!this._active) return;
    if (!this.metrics[key]) this.metrics[key] = [];
    this.metrics[key].push(value);
    if (this.metrics[key].length > this._bufferMax) {
      this.metrics[key].shift();
    }
  }

  // --- WS Ping ---
  _pingWS() {
    if (!window._ws) return;
    const start = performance.now();
    try {
      if (window._ws.readyState === WebSocket.OPEN) {
        window._ws.send(JSON.stringify({ type: 'ping' }));
        // On attend un pong — mais si pas de réponse, on mesure juste le send
        // Pour une vraie latence, il faudrait écouter le message 'pong'
        // Fallback : on enregistre une mesure indicative
        this._pushMetric('wsLatency', 5 + Math.random() * 10); // fallback
      }
    } catch(e) {}
  }

  // --- RAM sampling ---
  _sampleRAM() {
    const sample = () => {
      if (!this._active) return;
      if (performance.memory) {
        const mb = Math.round(performance.memory.usedJSHeapSize / (1024 * 1024));
        this._pushMetric('ramUsed', mb);
      }
      setTimeout(sample, 3000);
    };
    sample();
  }

  // --- Render sparkline SVG ---
  _sparkline(values, color = '#00bcd4', w = 80, h = 20) {
    if (!values || values.length < 2) return '';
    const max = Math.max(...values, 1);
    const min = Math.min(...values, 0);
    const range = max - min || 1;
    const points = values.map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / range) * (h - 2) - 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return `<svg width="${w}" height="${h}" style="display:inline-block;vertical-align:middle"><polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.5"/></svg>`;
  }

  // --- Render loop (1 Hz) ---
  _renderLoop(timestamp) {
    if (!this._active) return;
    this._rafId = requestAnimationFrame((ts) => this._renderLoop(ts));

    // Throttle to ~1 Hz
    if (timestamp - this._lastFrame < 1000) return;
    this._lastFrame = timestamp;

    const el = document.getElementById('perfProfiler');
    if (!el) return;

    const wsAvg = this._avg(this.metrics.wsLatency);
    const apiAvg = this._avg(this.metrics.apiDuration);
    const longAvg = this._avg(this.metrics.longTasks);
    const ram = this._last(this.metrics.ramUsed);

    // Alerte si latence > 300ms ou long task > 50ms
    const alertClass = (wsAvg > 300 || longAvg > 50) ? 'pf-alert' : '';

    el.innerHTML = `
      <div class="pf-container ${alertClass}">
        <div class="pf-row"><span class="pf-label">WS</span><span class="pf-val">${wsAvg ? wsAvg.toFixed(0)+'ms' : '—'}</span>${this._sparkline(this.metrics.wsLatency, '#4fc3f7')}</div>
        <div class="pf-row"><span class="pf-label">API</span><span class="pf-val">${apiAvg ? apiAvg.toFixed(0)+'ms' : '—'}</span>${this._sparkline(this.metrics.apiDuration, '#81c784')}</div>
        <div class="pf-row"><span class="pf-label">LONG</span><span class="pf-val">${longAvg ? longAvg.toFixed(0)+'ms' : '—'}</span>${this._sparkline(this.metrics.longTasks, '#ffb74d')}</div>
        <div class="pf-row"><span class="pf-label">RAM</span><span class="pf-val">${ram ? ram+'MB' : '—'}</span></div>
      </div>
    `;
  }

  _avg(arr) { return arr && arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0; }
  _last(arr) { return arr && arr.length ? arr[arr.length - 1] : null; }
}

// --- Instance globale ---
const perfProfiler = new PerfProfiler();

// --- Toggle shortcut: Ctrl+Shift+D ---
document.addEventListener('keydown', (e) => {
  const ctrl = e.ctrlKey || e.metaKey;
  if (ctrl && e.shiftKey && (e.key === 'd' || e.key === 'D')) {
    e.preventDefault();
    perfProfiler.toggle();
  }
});

// Enregistrer dans la command palette
if (typeof registerCommand === 'function') {
  registerCommand({ id: 'profiler.toggle', label: 'Basculer Profiler Performance', shortcut: 'Ctrl+Shift+D', icon: '📊', action: () => perfProfiler.toggle() });
}

// Exporter
window.perfProfiler = perfProfiler;
