/**
 * Sentinel API Client
 * Auto-detects base URL from window.location
 */
class _SentinelAPI {
  constructor() {
    this.baseUrl = window.location.origin;
  }

  async _request(method, path, body = null) {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body !== null) {
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(`${this.baseUrl}${path}`, opts);
    if (!resp.ok) {
      let msg = `API error ${resp.status}`;
      try {
        const err = await resp.json();
        msg = err.detail || err.message || msg;
      } catch (_) { /* ignore */ }
      throw new Error(msg);
    }
    if (resp.status === 204) return null;
    return resp.json();
  }

  // ── Scenarios ──
  getScenarios()              { return this._request('GET', '/api/scenarios'); }
  getScenario(id)             { return this._request('GET', `/api/scenarios/${encodeURIComponent(id)}`); }
  saveScenario(id, content, filename) {
    return this._request('PUT', `/api/scenarios/${encodeURIComponent(id)}`, { content, filename });
  }
  validateScenario(content)   { return this._request('POST', '/api/scenarios/validate', { content }); }
  deleteScenario(id)          { return this._request('DELETE', `/api/scenarios/${encodeURIComponent(id)}`); }

  // ── Runs ──
  startRun(scenarioId, modelEndpoint) {
    const body = { scenario_id: scenarioId };
    if (modelEndpoint) body.model_endpoint = modelEndpoint;
    return this._request('POST', '/api/runs', body);
  }
  startBatchRuns(options) {
    return this._request('POST', '/api/runs/batch', options);
  }
  getRuns()                   { return this._request('GET', '/api/runs'); }
  getRun(runId)               { return this._request('GET', `/api/runs/${encodeURIComponent(runId)}`); }
  getRunTrace(runId)          { return this._request('GET', `/api/runs/${encodeURIComponent(runId)}/trace`); }

  // ── Baselines ──
  getBaselines()               { return this._request('GET', '/api/baselines'); }
  getBaseline(label)           { return this._request('GET', `/api/baselines/${encodeURIComponent(label)}`); }
  deleteBaseline(label)        { return this._request('DELETE', `/api/baselines/${encodeURIComponent(label)}`); }
  getDiff(label1, label2)      { return this._request('GET', `/api/baselines/${encodeURIComponent(label1)}/diff/${encodeURIComponent(label2)}`); }

  // ── Model Endpoints ──
  getModelEndpoints()           { return this._request('GET', '/api/model-endpoints'); }
  addModelEndpoint(config)      { return this._request('POST', '/api/model-endpoints', config); }
  deleteModelEndpoint(id)       { return this._request('DELETE', `/api/model-endpoints/${encodeURIComponent(id)}`); }
  testModelEndpoint(id)         { return this._request('POST', `/api/model-endpoints/${encodeURIComponent(id)}/test`); }

  // ── Chaos ──
  getChaosInjectors()           { return this._request('GET', '/api/chaos/injectors'); }
  getChaosPresets()             { return this._request('GET', '/api/chaos/presets'); }
  previewChaosConfig(config)    { return this._request('POST', '/api/chaos/preview', config); }
  validateChaosConfig(config)   { return this._request('POST', '/api/chaos/validate', config); }

  // ── Reports ──
  getReportHtml(label)          { return `${this.baseUrl}/api/reports/${encodeURIComponent(label)}/html`; }
  getReportJunit(label)         { return `${this.baseUrl}/api/reports/${encodeURIComponent(label)}/junit`; }
  getComparisonReport(a, b)     { return `${this.baseUrl}/api/reports/compare/${encodeURIComponent(a)}/${encodeURIComponent(b)}/html`; }

  // ── Governance ──
  getGovernance()               { return this._request('GET', '/api/governance'); }
  runGovernanceAudit(diaryDate) { return this._request('POST', '/api/governance/audit', { diary_date: diaryDate }); }
}

var SentinelAPI = new _SentinelAPI();
window.SentinelAPI = SentinelAPI;
