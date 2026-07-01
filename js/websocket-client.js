/**
 * RealiaWebSocketClient — Connexion WS temps réel avec fallback polling.
 * Événements : task_started, task_progress, task_completed, task_failed.
 * Reconnexion automatique avec backoff exponentiel (1s, 2s, 4s, 8s, 16s).
 */
class RealiaWebSocketClient {
  constructor(taskId, callbacks) {
    this.taskId = taskId;
    this.callbacks = callbacks || {};
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.fallbackPollingActive = false;
  }

  async connect() {
    const wsUrl = `ws://${window.location.hostname}:8092/ws/task/${this.taskId}`;
    try {
      this.ws = new WebSocket(wsUrl);
    } catch (e) {
      console.error('[WS] Échec création WebSocket:', e);
      this.activateFallbackPolling();
      return;
    }
    this.ws.onopen = () => {
      console.log('[WS] Connecté pour tâche', this.taskId);
      this.reconnectAttempts = 0;
      if (this.callbacks.onOpen) this.callbacks.onOpen();
    };
    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleMessage(msg);
      } catch (e) {
        console.error('[WS] Parse erreur:', e);
      }
    };
    this.ws.onclose = () => {
      console.warn('[WS] Déconnecté pour tâche', this.taskId);
      if (!this.fallbackPollingActive) this.attemptReconnect();
    };
    this.ws.onerror = () => {
      console.error('[WS] Erreur pour tâche', this.taskId);
    };
  }

  handleMessage(msg) {
    if (msg.event === 'task_started' && this.callbacks.onStart) {
      this.callbacks.onStart(msg.data);
    } else if (msg.event === 'task_progress' && this.callbacks.onProgress) {
      this.callbacks.onProgress(msg.data);
    } else if (msg.event === 'task_completed' && this.callbacks.onComplete) {
      this.callbacks.onComplete(msg.data);
      this.close();
    } else if (msg.event === 'task_failed' && this.callbacks.onError) {
      this.callbacks.onError(msg.data);
      this.close();
    }
  }

  attemptReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[WS] Max reconnexions atteint, fallback polling');
      this.activateFallbackPolling();
      return;
    }
    const delay = Math.pow(2, this.reconnectAttempts) * 1000;
    this.reconnectAttempts++;
    console.log(`[WS] Reconnexion ${this.reconnectAttempts}/${this.maxReconnectAttempts} dans ${delay}ms`);
    setTimeout(() => this.connect(), delay);
  }

  activateFallbackPolling() {
    this.fallbackPollingActive = true;
    if (this.callbacks.onFallback) this.callbacks.onFallback();
  }

  close() {
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
  }
}

window.RealiaWebSocketClient = RealiaWebSocketClient;
