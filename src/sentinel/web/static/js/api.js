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
    return resp.json();
  }

  // Scenarios
  getScenarios()        { return this._request('GET', '/api/scenarios'); }
  getScenario(id)       { return this._request('GET', `/api/scenarios/${id}`); }

  // Runs
  startRun(scenarioId, modelEndpoint) {
    const body = { scenario_id: scenarioId };
    if (modelEndpoint) body.model_endpoint = modelEndpoint;
    return this._request('POST', '/api/runs', body);
  }
  getRuns()             { return this._request('GET', '/api/runs'); }
  getRun(runId)         { return this._request('GET', `/api/runs/${runId}`); }
  getRunTrace(runId)    { return this._request('GET', `/api/runs/${runId}/trace`); }

  // Baselines
  getBaselines()               { return this._request('GET', '/api/baselines'); }
  getBaseline(label)           { return this._request('GET', `/api/baselines/${label}`); }
  deleteBaseline(label)        { return this._request('DELETE', `/api/baselines/${label}`); }
  getDiff(label1, label2)      { return this._request('GET', `/api/baselines/${label1}/diff/${label2}`); }

  // Model Endpoints
  getModelEndpoints()           { return this._request('GET', '/api/model-endpoints'); }
  addModelEndpoint(config)      { return this._request('POST', '/api/model-endpoints', config); }
  deleteModelEndpoint(id)       { return this._request('DELETE', `/api/model-endpoints/${id}`); }
  testModelEndpoint(id)         { return this._request('POST', `/api/model-endpoints/${id}/test`); }
}

var SentinelAPI = new _SentinelAPI();
window.SentinelAPI = SentinelAPI;
