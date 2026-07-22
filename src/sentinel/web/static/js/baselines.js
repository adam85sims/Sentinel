/**
 * Sentinel Baselines Page
 */
function renderBaselines() {
  const content = document.getElementById('app-content');
  content.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">
        <svg width="24" height="24" viewBox="0 0 16 16" fill="currentColor"><path d="M7.068.727a.5.5 0 0 1 .884 0l4.5 7.5A.5.5 0 0 1 12 8.5v7a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5V11H8v3.5a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-7a.5.5 0 0 1 .168-.37l4.5-7.5z"/></svg>
        Baselines
      </h1>
      <p class="page-subtitle">Saved test results for comparison</p>
    </div>

    <div class="section-header">
      <h2 class="section-title">Compare Baselines</h2>
    </div>
    <div class="compare-bar" id="compare-bar">
      <label>Baseline A:</label>
      <select class="form-select" id="baseline-a"><option value="">Select…</option></select>
      <label>vs</label>
      <select class="form-select" id="baseline-b"><option value="">Select…</option></select>
      <button class="btn btn-primary btn-sm" id="compare-btn" disabled onclick="showDiff()">Compare</button>
    </div>
    <div id="diff-container"></div>

    <div class="section-header">
      <h2 class="section-title">All Baselines</h2>
    </div>
    <div id="baselines-loading" class="loading-placeholder">
      <div class="spinner"></div>
      <p>Loading baselines…</p>
    </div>
    <div id="baselines-content" class="hidden"></div>
  `;
  loadBaselines();
}

async function loadBaselines() {
  try {
    const data = await SentinelAPI.getBaselines();
    const baselines = Array.isArray(data) ? data : (data.baselines || []);

    document.getElementById('baselines-loading').classList.add('hidden');
    const bc = document.getElementById('baselines-content');
    bc.classList.remove('hidden');

    // Populate compare dropdowns
    const selA = document.getElementById('baseline-a');
    const selB = document.getElementById('baseline-b');
    for (const b of baselines) {
      const label = b.label || b.name || b.id;
      const opt = `<option value="${escapeHtml(label)}">${escapeHtml(label)}</option>`;
      selA.innerHTML += opt;
      selB.innerHTML += opt;
    }
    selA.addEventListener('change', updateCompareBtn);
    selB.addEventListener('change', updateCompareBtn);

    if (baselines.length === 0) {
      bc.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">📊</div>
          <div class="empty-state-title">No baselines saved</div>
          <div class="empty-state-text">Save a run as a baseline to compare results over time.</div>
        </div>
      `;
      return;
    }

    bc.innerHTML = `
      <div class="card-grid">
        ${baselines.map(b => {
          const label = b.label || b.name || b.id;
          const runCount = b.run_count || (b.results ? b.results.length : 0);
          const passCount = b.pass_count || 0;
          const failCount = b.fail_count || 0;
          return `
            <div class="card">
              <div class="card-header">
                <div class="card-title">${escapeHtml(label)}</div>
                <button class="btn btn-danger btn-sm" onclick="deleteBaseline('${escapeHtml(label)}')">Delete</button>
              </div>
              <div class="card-description text-mono text-sm">${b.created_at ? formatTime(b.created_at) : '—'}</div>
              <div class="flex gap-md text-sm">
                <span class="text-pass">✓ ${passCount} pass</span>
                <span class="text-fail">✗ ${failCount} fail</span>
                <span class="text-muted">${runCount} total</span>
              </div>
              <div class="flex gap-sm mt-sm">
                <a href="${SentinelAPI.getReportHtml(label)}" target="_blank" class="btn btn-ghost btn-sm" title="Download HTML Report">HTML</a>
                <a href="${SentinelAPI.getReportJunit(label)}" target="_blank" class="btn btn-ghost btn-sm" title="Download JUnit XML">JUnit</a>
              </div>
            </div>
          `;
        }).join('')}
      </div>
    `;
  } catch (err) {
    document.getElementById('baselines-loading').classList.add('hidden');
    document.getElementById('baselines-content').classList.remove('hidden');
    document.getElementById('baselines-content').innerHTML = `
      <div class="error-banner">
        <span class="error-banner-text">Failed to load baselines: ${escapeHtml(err.message)}</span>
        <button class="btn btn-ghost btn-sm" onclick="loadBaselines()">Retry</button>
      </div>
    `;
  }
}

function updateCompareBtn() {
  const a = document.getElementById('baseline-a').value;
  const b = document.getElementById('baseline-b').value;
  document.getElementById('compare-btn').disabled = !(a && b && a !== b);
}

async function showDiff() {
  const labelA = document.getElementById('baseline-a').value;
  const labelB = document.getElementById('baseline-b').value;
  if (!labelA || !labelB || labelA === labelB) return;

  const diffContainer = document.getElementById('diff-container');
  diffContainer.innerHTML = '<div class="loading-placeholder"><div class="spinner"></div><p>Loading diff…</p></div>';

  try {
    const diff = await SentinelAPI.getDiff(labelA, labelB);
    renderDiff(labelA, labelB, diff);
  } catch (err) {
    diffContainer.innerHTML = `
      <div class="error-banner">
        <span class="error-banner-text">Failed to load diff: ${escapeHtml(err.message)}</span>
      </div>
    `;
  }
}

function renderDiff(labelA, labelB, diffData) {
  const container = document.getElementById('diff-container');
  const items = diffData.items || diffData.deltas || diffData.results || [];
  const changes = diffData.changes || items;

  if (changes.length === 0) {
    container.innerHTML = `
      <div class="card mt-md">
        <div class="empty-state" style="padding:1.5rem;">
          <div class="text-muted">No differences found between ${escapeHtml(labelA)} and ${escapeHtml(labelB)}</div>
        </div>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div class="table-container mt-md">
      <table>
        <thead>
          <tr>
            <th>Scenario</th>
            <th>${escapeHtml(labelA)}</th>
            <th>${escapeHtml(labelB)}</th>
            <th>Delta</th>
          </tr>
        </thead>
        <tbody>
          ${changes.map(c => {
            const scenario = c.scenario || c.scenario_name || c.scenario_id || '—';
            const resultA = c.result_a || c.baseline_a || c.before || '—';
            const resultB = c.result_b || c.baseline_b || c.after || '—';
            const delta = c.delta || c.change || c.status || '—';
            const deltaCls = deltaBadgeClass(delta);
            return `
              <tr>
                <td>${escapeHtml(scenario)}</td>
                <td>${resultBadge(resultA)}</td>
                <td>${resultBadge(resultB)}</td>
                <td><span class="badge ${deltaCls}">${escapeHtml(delta)}</span></td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function deltaBadgeClass(delta) {
  const map = {
    'NEW_PASS': 'badge-new-pass',
    'NEW_FAIL': 'badge-new-fail',
    'STILL_PASS': 'badge-still-pass',
    'STILL_FAIL': 'badge-still-fail',
    'NEW_SCENARIO': 'badge-new-scenario',
    'REMOVED': 'badge-removed',
    'added': 'badge-new-scenario',
    'removed': 'badge-removed',
    'improved': 'badge-new-pass',
    'regressed': 'badge-new-fail',
  };
  return map[String(delta).toUpperCase()] || map[delta] || 'badge-neutral';
}

function resultBadge(result) {
  const r = String(result).toLowerCase();
  if (r === 'pass' || r === 'passed' || r === 'true') return `<span class="badge badge-pass">Pass</span>`;
  if (r === 'fail' || r === 'failed' || r === 'false') return `<span class="badge badge-fail">Fail</span>`;
  return `<span class="badge badge-neutral">${escapeHtml(String(result))}</span>`;
}

async function deleteBaseline(label) {
  if (!confirm(`Delete baseline "${label}"? This cannot be undone.`)) return;
  try {
    await SentinelAPI.deleteBaseline(label);
    appendToLog({ level: 'info', message: `Deleted baseline: ${label}` });
    loadBaselines();
  } catch (err) {
    appendToLog({ level: 'error', message: `Failed to delete baseline: ${err.message}` });
  }
}

window.renderBaselines = renderBaselines;
window.renderDiff = renderDiff;
window.showDiff = showDiff;
window.deleteBaseline = deleteBaseline;
