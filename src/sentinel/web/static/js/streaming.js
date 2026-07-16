/**
 * Sentinel SSE Streaming Manager
 * Connects to /api/runs/{runId}/stream and dispatches events.
 */
class StreamManager {
  constructor() {
    this._eventSource = null;
    this._callbacks = [];
    this._runId = null;
    this._retryTimeout = null;
    this._retryDelay = 2000;
    this._maxRetryDelay = 30000;
    this._intentionalClose = false;
  }

  connect(runId) {
    this.disconnect();
    this._runId = runId;
    this._intentionalClose = false;
    this._connectSSE();
  }

  _connectSSE() {
    if (!this._runId || this._intentionalClose) return;

    const url = `${window.location.origin}/api/runs/${this._runId}/stream`;
    this._eventSource = new EventSource(url);

    this._eventSource.onmessage = (event) => {
      this._retryDelay = 2000; // reset on successful message
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (_) {
        data = { raw: event.data };
      }
      this._dispatch(data);
    };

    this._eventSource.onerror = () => {
      if (this._intentionalClose) return;
      this._eventSource.close();
      this._retryTimeout = setTimeout(() => {
        this._retryDelay = Math.min(this._retryDelay * 2, this._maxRetryDelay);
        this._connectSSE();
      }, this._retryDelay);
    };
  }

  disconnect() {
    this._intentionalClose = true;
    if (this._retryTimeout) {
      clearTimeout(this._retryTimeout);
      this._retryTimeout = null;
    }
    if (this._eventSource) {
      this._eventSource.close();
      this._eventSource = null;
    }
    this._runId = null;
  }

  onEvent(callback) {
    this._callbacks.push(callback);
    return () => {
      this._callbacks = this._callbacks.filter(cb => cb !== callback);
    };
  }

  _dispatch(data) {
    for (const cb of this._callbacks) {
      try { cb(data); } catch (e) { console.error('Stream callback error:', e); }
    }
  }

  get isConnected() {
    return this._eventSource !== null && this._eventSource.readyState === EventSource.OPEN;
  }
}

/**
 * Append streaming events to the live log console
 */
function appendToLog(entry) {
  const logEntries = document.getElementById('log-entries');
  if (!logEntries) return;

  const el = document.createElement('div');
  const level = entry.level || entry.type || 'info';
  const cssClass = level === 'error' ? 'log-error'
    : level === 'warn' || level === 'warning' ? 'log-warn'
    : level === 'success' || level === 'pass' ? 'log-success'
    : 'log-info';

  el.className = `log-entry ${cssClass}`;

  const now = new Date();
  const time = now.toLocaleTimeString('en-US', { hour12: false });

  const msg = entry.message || entry.msg || entry.text || JSON.stringify(entry);
  el.innerHTML = `<span class="log-time">${time}</span><span class="log-msg">${escapeHtml(msg)}</span>`;
  logEntries.appendChild(el);

  // Auto-scroll to bottom
  const body = document.getElementById('log-console-body');
  if (body) body.scrollTop = body.scrollHeight;

  // Keep last 500 entries
  while (logEntries.children.length > 500) {
    logEntries.removeChild(logEntries.firstChild);
  }
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

window.StreamManager = StreamManager;
window.streamManager = new StreamManager();
window.appendToLog = appendToLog;
window.escapeHtml = escapeHtml;
