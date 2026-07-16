/**
 * Sentinel Scenarios Page
 */
function renderScenarios() {
  const content = document.getElementById('app-content');
  content.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">
        <svg width="24" height="24" viewBox="0 0 16 16" fill="currentColor"><path d="M2 2h4v4H2V2zm6 0h4v4H8V2zm-6 6h4v4H2V8zm6 0h4v4H8V8z" opacity=".7"/></svg>
        Scenarios
      </h1>
      <p class="page-subtitle">Agent behavioral test cases</p>
    </div>
    <div id="scenarios-loading" class="loading-placeholder">
      <div class="spinner"></div>
      <p>Loading scenarios…</p>
    </div>
    <div id="scenarios-content" class="hidden"></div>
  `;
  loadScenarios();
}

async function loadScenarios() {
  try {
    const data = await SentinelAPI.getScenarios();
    const scenarios = Array.isArray(data) ? data : (data.scenarios || []);

    document.getElementById('scenarios-loading').classList.add('hidden');
    const sc = document.getElementById('scenarios-content');
    sc.classList.remove('hidden');

    if (scenarios.length === 0) {
      sc.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">📋</div>
          <div class="empty-state-title">No scenarios found</div>
          <div class="empty-state-text">Add YAML scenario files to your scenarios directory.</div>
        </div>
      `;
      return;
    }

    sc.innerHTML = `
      <div class="card-grid">
        ${scenarios.map(s => renderScenarioCard(s)).join('')}
      </div>
    `;
  } catch (err) {
    document.getElementById('scenarios-loading').classList.add('hidden');
    document.getElementById('scenarios-content').classList.remove('hidden');
    document.getElementById('scenarios-content').innerHTML = `
      <div class="error-banner">
        <span class="error-banner-text">Failed to load scenarios: ${escapeHtml(err.message)}</span>
        <button class="btn btn-ghost btn-sm" onclick="loadScenarios()">Retry</button>
      </div>
    `;
  }
}

function renderScenarioCard(s) {
  const id = s.id || s.name || s.scenario_id;
  const name = s.name || s.scenario_name || id;
  const desc = s.description || s.desc || '';
  const tags = s.tags || [];
  const taskPreview = s.task || s.instruction || '';
  const truncatedTask = taskPreview.length > 120 ? taskPreview.substring(0, 120) + '…' : taskPreview;

  return `
    <div class="card card-clickable" onclick="window.SentinelRouter.navigate('#/scenarios/${encodeURIComponent(id)}')">
      <div class="card-header">
        <div class="card-title">${escapeHtml(name)}</div>
      </div>
      ${desc ? `<div class="card-description">${escapeHtml(desc)}</div>` : ''}
      ${tags.length > 0 ? `
        <div class="tag-group mb-sm">
          ${tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}
        </div>
      ` : ''}
      ${truncatedTask ? `
        <div class="text-sm text-muted" style="font-family:var(--font-mono); white-space:pre-wrap; max-height:4rem; overflow:hidden;">${escapeHtml(truncatedTask)}</div>
      ` : ''}
      <div class="card-footer">
        <span class="text-xs text-subtle">${escapeHtml(String(id))}</span>
        <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); runScenario('${escapeHtml(id)}')">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor"><path d="M4 2l10 6-10 6V2z"/></svg>
          Run
        </button>
      </div>
    </div>
  `;
}

async function runScenario(scenarioId) {
  try {
    appendToLog({ level: 'info', message: `Starting run for scenario: ${scenarioId}` });
    const result = await SentinelAPI.startRun(scenarioId);
    const runId = result.run_id || result.id || result.run_id;
    appendToLog({ level: 'success', message: `Run started: ${runId}` });
    window.SentinelRouter.navigate(`#/runs/${runId}`);
  } catch (err) {
    appendToLog({ level: 'error', message: `Failed to start run: ${err.message}` });
    alert('Failed to start run: ' + err.message);
  }
}

function renderScenarioDetail(id) {
  const content = document.getElementById('app-content');
  content.innerHTML = `
    <div class="page-header">
      <div class="flex items-center gap-md">
        <a href="#/scenarios" class="btn btn-ghost btn-sm">← Back</a>
        <h1 class="page-title">Loading…</h1>
      </div>
    </div>
    <div id="scenario-detail-loading" class="loading-placeholder">
      <div class="spinner"></div>
    </div>
    <div id="scenario-detail-content" class="hidden"></div>
  `;
  loadScenarioDetail(id);
}

async function loadScenarioDetail(id) {
  try {
    const s = await SentinelAPI.getScenario(id);
    document.getElementById('scenario-detail-loading').classList.add('hidden');
    const dc = document.getElementById('scenario-detail-content');
    dc.classList.remove('hidden');

    const name = s.name || s.scenario_name || id;
    const desc = s.description || '';
    const tags = s.tags || [];
    const task = s.task || s.instruction || '';
    const yaml = s.yaml || s.raw_yaml || '';
    const assertions = s.assertions || [];

    document.querySelector('.page-title').textContent = name;

    dc.innerHTML = `
      <div class="flex items-center justify-between mb-lg" style="flex-wrap:wrap; gap:1rem;">
        <div>
          ${desc ? `<p class="text-muted">${escapeHtml(desc)}</p>` : ''}
          ${tags.length > 0 ? `
            <div class="tag-group mt-sm">
              ${tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}
            </div>
          ` : ''}
        </div>
        <button class="btn btn-primary" onclick="runScenario('${escapeHtml(id)}')">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 2l10 6-10 6V2z"/></svg>
          Run Scenario
        </button>
      </div>

      ${task ? `
        <div class="section-header">
          <h2 class="section-title">Task</h2>
        </div>
        <div class="yaml-preview">${escapeHtml(task)}</div>
      ` : ''}

      ${assertions.length > 0 ? `
        <div class="section-header">
          <h2 class="section-title">Assertions</h2>
        </div>
        <div class="card">
          ${assertions.map(a => `
            <div class="assertion-item">
              <span class="assertion-icon text-accent">✓</span>
              <span class="assertion-text text-sm">${escapeHtml(typeof a === 'string' ? a : JSON.stringify(a))}</span>
            </div>
          `).join('')}
        </div>
      ` : ''}

      ${yaml ? `
        <div class="section-header">
          <h2 class="section-title">Scenario YAML</h2>
        </div>
        <div class="yaml-preview">${escapeHtml(yaml)}</div>
      ` : `
        <div class="section-header">
          <h2 class="section-title">Scenario Data</h2>
        </div>
        <div class="yaml-preview">${escapeHtml(JSON.stringify(s, null, 2))}</div>
      `}
    `;
  } catch (err) {
    document.getElementById('scenario-detail-loading').classList.add('hidden');
    document.getElementById('scenario-detail-content').classList.remove('hidden');
    document.getElementById('scenario-detail-content').innerHTML = `
      <div class="error-banner">
        <span class="error-banner-text">Failed to load scenario: ${escapeHtml(err.message)}</span>
        <a href="#/scenarios" class="btn btn-ghost btn-sm">Back to Scenarios</a>
      </div>
    `;
  }
}

window.renderScenarios = renderScenarios;
window.renderScenarioDetail = renderScenarioDetail;
window.runScenario = runScenario;
