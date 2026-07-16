/**
 * Sentinel Runs Page
 */
function renderRuns() {
  const content = document.getElementById('app-content');
  content.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">
        <svg width="24" height="24" viewBox="0 0 16 16" fill="currentColor"><path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14zm0-1A6 6 0 1 0 8 2a6 6 0 0 0 0 12z"/><path d="M6.271 5.055a.5.5 0 0 1 .52.038l3.5 2.5a.5.5 0 0 1 0 .814l-3.5 2.5A.5.5 0 0 1 6 10.5v-5a.5.5 0 0 1 .271-.445z"/></svg>
        Runs
      </h1>
      <p class="page-subtitle">Test execution history</p>
    </div>
    <div id="runs-loading" class="loading-placeholder">
      <div class="spinner"></div>
      <p>Loading runs…</p>
    </div>
    <div id="runs-content" class="hidden"></div>
  `;
  loadRuns();
}

async function loadRuns() {
  try {
    const data = await SentinelAPI.getRuns();
    const runs = Array.isArray(data) ? data : (data.runs || []);

    document.getElementById('runs-loading').classList.add('hidden');
    const rc = document.getElementById('runs-content');
    rc.classList.remove('hidden');

    if (runs.length === 0) {
      rc.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">▶</div>
          <div class="empty-state-title">No runs yet</div>
          <div class="empty-state-text">Run a scenario from the Scenarios page to start testing.</div>
        </div>
      `;
      return;
    }

    rc.innerHTML = `
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Run ID</th>
              <th>Scenario</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Started</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${runs.map(r => {
              const rid = r.id || r.run_id;
              return `
                <tr>
                  <td><a class="table-link" href="#/runs/${encodeURIComponent(rid)}">${escapeHtml(String(rid).substring(0, 8))}</a></td>
                  <td>${escapeHtml(r.scenario_name || r.scenario_id || '—')}</td>
                  <td>${statusBadge(r.status)}</td>
                  <td class="mono">${r.duration ? formatDuration(r.duration) : '—'}</td>
                  <td class="mono text-sm">${r.started_at ? formatTime(r.started_at) : '—'}</td>
                  <td><a href="#/runs/${encodeURIComponent(rid)}" class="btn btn-ghost btn-sm">View</a></td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    `;
  } catch (err) {
    document.getElementById('runs-loading').classList.add('hidden');
    document.getElementById('runs-content').classList.remove('hidden');
    document.getElementById('runs-content').innerHTML = `
      <div class="error-banner">
        <span class="error-banner-text">Failed to load runs: ${escapeHtml(err.message)}</span>
        <button class="btn btn-ghost btn-sm" onclick="loadRuns()">Retry</button>
      </div>
    `;
  }
}

function renderRunDetail(runId) {
  const content = document.getElementById('app-content');
  content.innerHTML = `
    <div class="page-header">
      <div class="flex items-center gap-md">
        <a href="#/runs" class="btn btn-ghost btn-sm">← Back</a>
        <h1 class="page-title">Run ${escapeHtml(runId)}</h1>
      </div>
    </div>
    <div id="run-detail-loading" class="loading-placeholder">
      <div class="spinner"></div>
      <p>Loading run details…</p>
    </div>
    <div id="run-detail-content" class="hidden"></div>
  `;
  loadRunDetail(runId);
}

async function loadRunDetail(runId) {
  try {
    const run = await SentinelAPI.getRun(runId);
    document.getElementById('run-detail-loading').classList.add('hidden');
    const dc = document.getElementById('run-detail-content');
    dc.classList.remove('hidden');

    const rid = run.id || run.run_id || runId;
    const status = run.status || 'unknown';
    const scenarioName = run.scenario_name || run.scenario_id || '—';

    // Connect SSE for live updates
    window.streamManager.disconnect();
    if (status === 'queued' || status === 'running') {
      window.streamManager.connect(rid);
      window.streamManager.onEvent((data) => {
        appendToLog(data);
        // Try to refresh if run completes
        if (data.status === 'completed' || data.status === 'failed' || data.status === 'passed') {
          setTimeout(() => loadRunDetail(runId), 500);
        }
      });
    }

    document.querySelector('.page-title').textContent = `Run ${escapeHtml(String(rid).substring(0, 8))}`;

    let traceHtml = '';
    try {
      const trace = await SentinelAPI.getRunTrace(rid);
      traceHtml = renderTraceTimeline(trace);
    } catch (traceErr) {
      traceHtml = `<div class="text-muted text-sm">Trace not available: ${escapeHtml(traceErr.message)}</div>`;
    }

    dc.innerHTML = `
      <div class="flex items-center justify-between mb-lg" style="flex-wrap:wrap; gap:1rem;">
        <div class="flex items-center gap-md">
          ${statusBadge(status)}
          <span class="text-muted text-sm">Scenario: ${escapeHtml(scenarioName)}</span>
        </div>
        <div class="flex items-center gap-sm">
          <button class="btn btn-primary btn-sm" onclick="rerunScenario('${escapeHtml(run.scenario_id || '')}', '${escapeHtml(rid)}')">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor"><path d="M8 4.754a3.246 3.246 0 1 0 0 6.492 3.246 3.246 0 0 0 0-6.492zM5.754 8a2.246 2.246 0 1 1 4.492 0 2.246 2.246 0 0 1-4.492 0z"/><path d="M9.796 1.343c-.527-1.79-3.065-1.79-3.592 0l-.094.319a.873.873 0 0 1-1.255.52l-.292-.16c-1.64-.892-3.433.902-2.54 2.541l.159.292a.873.873 0 0 1-.52 1.255l-.319.094c-1.79.527-1.79 3.065 0 3.592l.319.094a.873.873 0 0 1 .52 1.255l-.16.292c-.892 1.64.901 3.434 2.541 2.54l.292-.159a.873.873 0 0 1 1.255.52l.094.319c.527 1.79 3.065 1.79 3.592 0l.094-.319a.873.873 0 0 1 1.255-.52l.292.16c1.64.892 3.434-.902 2.54-2.541l-.159-.292a.873.873 0 0 1 .52-1.255l.319-.094c1.79-.527 1.79-3.065 0-3.592l-.319-.094a.873.873 0 0 1-.52-1.255l.16-.292c.893-1.64-.902-3.433-2.541-2.54l-.292.159a.873.873 0 0 1-1.255-.52l-.094-.319z"/></svg>
            Re-run
          </button>
        </div>
      </div>

      <div class="stat-grid">
        <div class="stat-card">
          <div class="stat-label">Status</div>
          <div class="stat-value ${status === 'completed' || status === 'passed' ? 'pass' : status === 'failed' ? 'fail' : ''}">${escapeHtml(status)}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Duration</div>
          <div class="stat-value">${run.duration ? formatDuration(run.duration) : '—'}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Started</div>
          <div class="stat-value text-sm">${run.started_at ? formatTime(run.started_at) : '—'}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Completed</div>
          <div class="stat-value text-sm">${run.completed_at ? formatTime(run.completed_at) : '—'}</div>
        </div>
      </div>

      <div class="section-header">
        <h2 class="section-title">Trace</h2>
      </div>
      <div id="run-trace">
        ${traceHtml}
      </div>
    `;
  } catch (err) {
    document.getElementById('run-detail-loading').classList.add('hidden');
    document.getElementById('run-detail-content').classList.remove('hidden');
    document.getElementById('run-detail-content').innerHTML = `
      <div class="error-banner">
        <span class="error-banner-text">Failed to load run: ${escapeHtml(err.message)}</span>
        <a href="#/runs" class="btn btn-ghost btn-sm">Back to Runs</a>
      </div>
    `;
  }
}

function rerunScenario(scenarioId) {
  if (scenarioId) {
    runScenario(scenarioId);
  } else {
    window.SentinelRouter.navigate('#/scenarios');
  }
}

window.renderRuns = renderRuns;
window.renderRunDetail = renderRunDetail;
window.rerunScenario = rerunScenario;
