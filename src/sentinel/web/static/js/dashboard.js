/**
 * Sentinel Dashboard Page
 *
 * Shows stat cards, a pass/fail trend chart (SVG), recent runs table,
 * and quick-action buttons.
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

    const recentRuns = runsList.slice(0, 20);
    const completed = runsList.filter(r => r.status === 'completed' || r.status === 'failed' || r.status === 'passed');
    const passed = completed.filter(r => r.status === 'completed' || r.status === 'passed');
    const failed = completed.filter(r => r.status === 'failed');
    const passRate = completed.length > 0 ? Math.round((passed.length / completed.length) * 100) : 0;

    document.getElementById('dashboard-loading').classList.add('hidden');
    const dc = document.getElementById('dashboard-content');
    dc.classList.remove('hidden');

    // ── Stat cards ──
    dc.innerHTML = `
      <div class="stat-grid">
        <div class="stat-card">
          <div class="stat-label">Total Scenarios</div>
          <div class="stat-value accent">${scenariosList.length}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Pass Rate</div>
          <div class="stat-value ${passRate >= 80 ? 'pass' : passRate >= 50 ? 'warn' : 'fail'}">${completed.length > 0 ? passRate + '%' : '—'}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Failures</div>
          <div class="stat-value ${failed.length > 0 ? 'fail' : 'pass'}">${failed.length}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Baselines</div>
          <div class="stat-value">${baselinesList.length}</div>
        </div>
      </div>

      <!-- Trend chart -->
      ${completed.length > 0 ? `
        <div class="section-header">
          <h2 class="section-title">Pass Rate Trend</h2>
          <span class="text-muted text-sm">Last ${Math.min(completed.length, 20)} runs</span>
        </div>
        <div class="card" id="trend-chart-container">
          ${renderTrendChart(completed.slice(0, 20))}
        </div>
      ` : ''}

      <!-- Recent runs -->
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

      <!-- Quick actions -->
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

/**
 * Render an SVG trend chart showing pass rate over recent runs.
 * Each run gets a vertical bar: green for pass, red for fail.
 * A polyline connects the running pass rate %.
 */
function renderTrendChart(runs) {
  if (!runs || runs.length === 0) return '';

  const W = 700;   // chart width
  const H = 140;   // chart height
  const PAD = 40;   // left padding for y-axis labels
  const GAP = 6;   // gap between bars
  const barW = Math.max(8, Math.min(24, (W - PAD) / runs.length - GAP));

  // Compute running pass rate at each point
  let passCount = 0;
  const points = runs.map((r, i) => {
    const isPass = r.status === 'completed' || r.status === 'passed';
    if (isPass) passCount++;
    const rate = ((passCount / (i + 1)) * 100);
    return { isPass, rate, index: i };
  });

  // SVG polyline points for the trend line
  const polylinePoints = points.map(p => {
    const x = PAD + p.index * (barW + GAP) + barW / 2;
    const y = H - (p.rate / 100) * (H - 20);  // 20px top padding
    return `${x},${y}`;
  }).join(' ');

  // Y-axis labels
  const yLabels = [0, 25, 50, 75, 100].map(pct => {
    const y = H - (pct / 100) * (H - 20);
    return `<text x="${PAD - 8}" y="${y + 4}" class="trend-y-label" text-anchor="end">${pct}%</text>
            <line x1="${PAD}" y1="${y}" x2="${W}" y2="${y}" class="trend-gridline"/>`;
  }).join('');

  // Bars
  const bars = points.map((p, i) => {
    const x = PAD + i * (barW + GAP);
    const barH = p.isPass ? H : H * 0.3;
    const color = p.isPass ? 'var(--pass)' : 'var(--fail)';
    const opacity = p.isPass ? '0.35' : '0.5';
    return `<rect x="${x}" y="${H - barH}" width="${barW}" height="${barH}" rx="2" fill="${color}" opacity="${opacity}" class="trend-bar"/>`;
  }).join('');

  // Final pass rate label
  const lastRate = points[points.length - 1].rate;
  const lastX = PAD + (runs.length - 1) * (barW + GAP) + barW / 2;
  const lastY = H - (lastRate / 100) * (H - 20);

  return `
    <div class="trend-chart-wrapper" style="overflow-x:auto;">
      <svg viewBox="0 0 ${W} ${H + 10}" width="100%" height="${H + 10}" preserveAspectRatio="xMidYMid meet" style="min-width:300px;">
        <defs>
          <linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.3"/>
            <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.02"/>
          </linearGradient>
        </defs>

        <!-- Grid -->
        ${yLabels}

        <!-- Bars -->
        ${bars}

        <!-- Trend line -->
        <polyline points="${polylinePoints}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>

        <!-- Fill under the line -->
        <polygon points="${polylinePoints} ${lastX},${H} ${PAD + barW / 2},${H}" fill="url(#trend-fill)"/>

        <!-- Final rate label -->
        <circle cx="${lastX}" cy="${lastY}" r="4" fill="var(--accent)"/>
        <text x="${lastX}" y="${lastY - 10}" class="trend-final-label" text-anchor="middle">${Math.round(lastRate)}%</text>
      </svg>
    </div>
  `;
}

// ── Helpers (exposed globally) ──

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
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
    });
  } catch (_) {
    return ts;
  }
}

window.renderDashboard = renderDashboard;
window.statusBadge = statusBadge;
window.formatDuration = formatDuration;
window.formatTime = formatTime;
