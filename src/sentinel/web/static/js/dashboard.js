/**
 * Sentinel Dashboard Page
 */
function renderDashboard() {
  const content = document.getElementById('app-content');
  content.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">
        <svg width="24" height="24" viewBox="0 0 16 16" fill="currentColor"><path d="M1 2.5A1.5 1.5 0 0 1 2.5 1h3A1.5 1.5 0 0 1 7 2.5v3A1.5 1.5 0 0 1 5.5 7h-3A1.5 1.5 0 0 1 1 5.5v-3zm8 0A1.5 1.5 0 0 1 10.5 1h3A1.5 1.5 0 0 1 15 2.5v3A1.5 1.5 0 0 1 13.5 7h-3A1.5 1.5 0 0 1 9 5.5v-3zm-8 8A1.5 1.5 0 0 1 2.5 9h3A1.5 1.5 0 0 1 7 10.5v3A1.5 1.5 0 0 1 5.5 15h-3A1.5 1.5 0 0 1 1 13.5v-3zm8 0A1.5 1.5 0 0 1 10.5 9h3a1.5 1.5 0 0 1 1.5 1.5v3a1.5 1.5 0 0 1-1.5 1.5h-3A1.5 1.5 0 0 1 9 13.5v-3z"/></svg>
        Dashboard
      </h1>
      <p class="page-subtitle">Overview of your agent testing environment</p>
    </div>
    <div id="dashboard-loading" class="loading-placeholder">
      <div class="spinner"></div>
      <p>Loading dashboard…</p>
    </div>
    <div id="dashboard-content" class="hidden"></div>
  `;

  loadDashboardData();
}

async function loadDashboardData() {
  try {
    const [scenarios, runs, baselines] = await Promise.all([
      SentinelAPI.getScenarios().catch(() => []),
      SentinelAPI.getRuns().catch(() => []),
      SentinelAPI.getBaselines().catch(() => []),
    ]);

    const scenariosList = Array.isArray(scenarios) ? scenarios : (scenarios.scenarios || []);
    const runsList = Array.isArray(runs) ? runs : (runs.runs || []);
    const baselinesList = Array.isArray(baselines) ? baselines : (baselines.baselines || []);

    const recentRuns = runsList.slice(0, 10);
    const completed = runsList.filter(r => r.status === 'completed' || r.status === 'failed' || r.status === 'passed');
    const passed = completed.filter(r => r.status === 'completed' || r.status === 'passed');
    const failed = completed.filter(r => r.status === 'failed');
    const passRate = completed.length > 0 ? Math.round((passed.length / completed.length) * 100) : 0;

    document.getElementById('dashboard-loading').classList.add('hidden');
    const dc = document.getElementById('dashboard-content');
    dc.classList.remove('hidden');

    // Stat cards
    dc.innerHTML = `
      <div class="stat-grid">
        <div class="stat-card">
          <div class="stat-label">Total Scenarios</div>
          <div class="stat-value accent">${scenariosList.length}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Recent Pass Rate</div>
          <div class="stat-value ${passRate >= 80 ? 'pass' : passRate >= 50 ? 'warn' : 'fail'}">${completed.length > 0 ? passRate + '%' : '—'}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Recent Failures</div>
          <div class="stat-value ${failed.length > 0 ? 'fail' : 'pass'}">${failed.length}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Total Runs</div>
          <div class="stat-value">${runsList.length}</div>
        </div>
      </div>

      <div class="section-header">
        <h2 class="section-title">Recent Runs</h2>
      </div>
      ${recentRuns.length === 0 ? `
        <div class="empty-state">
          <div class="empty-state-icon">▶</div>
          <div class="empty-state-title">No runs yet</div>
          <div class="empty-state-text">Run a scenario to see results here.</div>
        </div>
      ` : `
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Scenario</th>
                <th>Status</th>
                <th>Duration</th>
                <th>Started</th>
              </tr>
            </thead>
            <tbody>
              ${recentRuns.map(r => `
                <tr>
                  <td><a class="table-link" href="#/runs/${r.id || r.run_id}">${escapeHtml(r.scenario_name || r.scenario_id || 'Unknown')}</a></td>
                  <td>${statusBadge(r.status)}</td>
                  <td class="mono">${r.duration ? formatDuration(r.duration) : '—'}</td>
                  <td class="mono text-sm">${r.started_at ? formatTime(r.started_at) : '—'}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `}

      ${completed.length > 0 ? `
        <div class="section-header">
          <h2 class="section-title">Pass / Fail Overview</h2>
        </div>
        <div class="card">
          <div class="bar-chart">
            ${recentRuns.map(r => {
              const isPass = r.status === 'completed' || r.status === 'passed';
              const isFail = r.status === 'failed';
              const cls = isPass ? 'pass' : isFail ? 'fail' : '';
              return `<div class="bar-chart-bar ${cls}" style="height: ${cls ? '100%' : '20%'}" title="${escapeHtml(r.scenario_name || r.scenario_id || 'Unknown')}: ${r.status}"></div>`;
            }).join('')}
          </div>
          <div class="bar-chart-legend">
            <span class="bar-chart-legend-item"><span class="bar-chart-legend-dot" style="background:var(--pass)"></span> Pass</span>
            <span class="bar-chart-legend-item"><span class="bar-chart-legend-dot" style="background:var(--fail)"></span> Fail</span>
            <span class="bar-chart-legend-item"><span class="bar-chart-legend-dot" style="background:var(--fg-subtle)"></span> Other</span>
          </div>
        </div>
      ` : ''}

      <div class="section-header">
        <h2 class="section-title">Quick Actions</h2>
      </div>
      <div class="flex gap-md">
        <a href="#/scenarios" class="btn btn-primary">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M8 2a.5.5 0 0 1 .5.5v5h5a.5.5 0 0 1 0 1h-5v5a.5.5 0 0 1-1 0v-5h-5a.5.5 0 0 1 0-1h5v-5A.5.5 0 0 1 8 2z"/></svg>
          View Scenarios
        </a>
        <a href="#/runs" class="btn btn-ghost">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14zm0-1A6 6 0 1 0 8 2a6 6 0 0 0 0 12z"/></svg>
          View Runs
        </a>
        <a href="#/baselines" class="btn btn-ghost">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M7.068.727a.5.5 0 0 1 .884 0l4.5 7.5A.5.5 0 0 1 12 8.5v7a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5V11H8v3.5a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-7a.5.5 0 0 1 .168-.37l4.5-7.5z"/></svg>
          View Baselines
        </a>
      </div>
    `;
  } catch (err) {
    document.getElementById('dashboard-loading').classList.add('hidden');
    document.getElementById('dashboard-content').classList.remove('hidden');
    document.getElementById('dashboard-content').innerHTML = `
      <div class="error-banner">
        <span class="error-banner-text">Failed to load dashboard: ${escapeHtml(err.message)}</span>
        <button class="btn btn-ghost btn-sm" onclick="loadDashboardData()">Retry</button>
      </div>
    `;
  }
}

function statusBadge(status) {
  const map = {
    'passed':  'badge-pass',
    'completed': 'badge-pass',
    'failed':  'badge-fail',
    'running': 'badge-running',
    'queued':  'badge-queued',
    'error':   'badge-fail',
  };
  const cls = map[status] || 'badge-neutral';
  return `<span class="badge ${cls}">${escapeHtml(status || 'unknown')}</span>`;
}

function formatDuration(seconds) {
  if (typeof seconds !== 'number') return '—';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function formatTime(ts) {
  try {
    const d = new Date(ts);
    return d.toLocaleString('en-US', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  } catch (_) {
    return ts;
  }
}

window.renderDashboard = renderDashboard;
window.statusBadge = statusBadge;
window.formatDuration = formatDuration;
window.formatTime = formatTime;
