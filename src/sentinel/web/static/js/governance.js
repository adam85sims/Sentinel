/**
 * Sentinel WebUI — Governance & Compliance Dashboard
 *
 * Displays audit scores, recent findings, and audit history.
 * Fetches real compliance data from the /api/governance endpoints.
 */
function renderGovernance() {
  const content = document.getElementById('app-content');
  if (!content) return;

  content.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">
        <svg width="24" height="24" viewBox="0 0 16 16" fill="currentColor"><path d="M8 1a2 2 0 0 1 2 2v4H6V3a2 2 0 0 1 2-2zm3 6V3a3 3 0 0 0-6 0v4a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2zM6 9a1 1 0 0 1 1 1v.01a1 1 0 1 1-2 0V10a1 1 0 0 1 1-1z"/></svg>
        Governance &amp; Compliance
      </h1>
      <p class="page-subtitle">Audit results, findings, and compliance status</p>
    </div>

    <div id="gov-loading" class="loading-placeholder">
      <div class="spinner"></div>
      <p>Loading compliance status…</p>
    </div>
    <div id="gov-content" class="hidden"></div>
  `;
  loadGovernance();
}

async function loadGovernance() {
  try {
    const data = await SentinelAPI.getGovernance();
    
    document.getElementById('gov-loading').classList.add('hidden');
    const govContent = document.getElementById('gov-content');
    govContent.classList.remove('hidden');

    const severityIcon = (s) => {
      switch (s) {
        case 'CRITICAL': return '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8.982 1.566a1.13 1.13 0 0 0-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/></svg>';
        case 'WARNING':  return '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8.982 1.566a1.13 1.13 0 0 0-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/></svg>';
        default:         return '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M16 8A8 8 0 1 1 0 8a8 8 0 0 1 16 0zm-3.97-3.03a.75.75 0 0 0-1.08.022L7.477 9.417 5.384 7.323a.75.75 0 0 0-1.06 1.06L6.97 11.03a.75.75 0 0 0 1.079-.02l3.992-4.99a.75.75 0 0 0-.01-1.05z"/></svg>';
      }
    };

    const severityClass = (s) => {
      switch (s) {
        case 'CRITICAL': return 'badge-fail';
        case 'WARNING':  return 'badge-running';
        default:         return 'badge-pass';
      }
    };

    const statusBadge = (s) => {
      const cls = s === 'PASS' ? 'badge-pass' : 'badge-fail';
      return `<span class="badge ${cls}">${escapeHtml(s)}</span>`;
    };

    const formatTs = (ts) => {
      if (!ts) return 'Never';
      try {
        const d = new Date(ts);
        return d.toLocaleString('en-US', {
          month: 'short', day: 'numeric', year: 'numeric',
          hour: '2-digit', minute: '2-digit', hour12: false,
        });
      } catch (_) { return ts; }
    };

    const escapeHtml = (text) => (window.SentinelApp?.escapeHtml || (x => x))(text);

    govContent.innerHTML = `
      <!-- Scorecard -->
      <div class="gov-scorecard">
        <div class="gov-score-card">
          <div class="score-value">${data.total_audits}</div>
          <div class="score-label">Total Audits</div>
        </div>
        <div class="gov-score-card">
          <div class="score-value ${data.total_audits > 0 ? (data.pass_rate >= 80 ? 'pass' : data.pass_rate >= 50 ? 'warn' : 'fail') : ''}">${data.total_audits > 0 ? data.pass_rate + '%' : '—'}</div>
          <div class="score-label">Pass Rate (${data.passed_audits}/${data.total_audits})</div>
        </div>
        <div class="gov-score-card">
          <div class="score-value ${data.total_audits > 0 ? (data.critical_findings > 0 ? 'fail' : 'pass') : ''}">${data.total_audits > 0 ? data.critical_findings : '—'}</div>
          <div class="score-label">Critical Findings</div>
        </div>
        <div class="gov-score-card">
          <div class="score-value">${formatTs(data.last_audit)}</div>
          <div class="score-label">Last Audit</div>
        </div>
      </div>

      <!-- Findings -->
      <div class="section-header">
        <h2 class="section-title">Recent Findings</h2>
        <span class="text-muted text-sm">${data.findings.length} finding${data.findings.length !== 1 ? 's' : ''}</span>
      </div>
      <div class="card">
        ${data.findings.length === 0 ? `
          <p class="text-muted text-sm" style="margin: 0.5rem 0; padding: 0.5rem;">No discrepancies found in the latest audit.</p>
        ` : data.findings.map((f) => `
          <div class="finding-item" data-finding-id="${escapeHtml(f.id)}">
            <div class="finding-icon ${severityClass(f.severity)}">
              ${severityIcon(f.severity)}
            </div>
            <div class="finding-text">
              <span class="badge ${severityClass(f.severity)}" style="margin-right:0.5rem">${escapeHtml(f.severity)}</span>
              ${escapeHtml(f.description)}
            </div>
          </div>
        `).join('')}
      </div>

      <!-- Run Audit -->
      <div class="flex gap-md mt-1">
        <button class="btn btn-primary" id="gov-run-audit-btn">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14zm0 1A8 8 0 1 0 8 0a8 8 0 0 0 0 16z"/><path d="M6.271 5.055a.5.5 0 0 1 .52.038l3.5 2.5a.5.5 0 0 1 0 .814l-3.5 2.5A.5.5 0 0 1 6 10.5v-5a.5.5 0 0 1 .271-.445z"/></svg>
          Run Audit
        </button>
      </div>

      <!-- Audit History -->
      <div class="section-header mt-1">
        <h2 class="section-title">Audit History</h2>
      </div>
      ${data.history.length === 0 ? `
        <div class="empty-state">
          <div class="empty-state-icon">📋</div>
          <div class="empty-state-title">No audits yet</div>
          <div class="empty-state-text">Run an audit to see history here.</div>
        </div>
      ` : `
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Audit</th>
                <th>Date</th>
                <th>Status</th>
                <th>Findings</th>
              </tr>
            </thead>
            <tbody>
              ${data.history.map(h => `
                <tr>
                  <td class="mono">${escapeHtml(h.id)}</td>
                  <td class="mono text-sm">${formatTs(h.date)}</td>
                  <td>${statusBadge(h.status)}</td>
                  <td class="mono">${h.findings}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `}
    `;

    // Wire up Run Audit button
    document.getElementById('gov-run-audit-btn')?.addEventListener('click', async () => {
      const showToast = (msg, type) => (window.SentinelApp?.showToast || console.log)(msg, type);
      showToast('Running governance audit...', 'info');
      try {
        const btn = document.getElementById('gov-run-audit-btn');
        if (btn) btn.disabled = true;
        
        await SentinelAPI.runGovernanceAudit();
        showToast('Audit complete!', 'success');
        
        // Refresh
        renderGovernance();
      } catch (err) {
        showToast('Audit failed: ' + err.message, 'error');
        const btn = document.getElementById('gov-run-audit-btn');
        if (btn) btn.disabled = false;
      }
    });

  } catch (err) {
    const escapeHtml = (text) => (window.SentinelApp?.escapeHtml || (x => x))(text);
    document.getElementById('gov-loading').classList.add('hidden');
    const govContent = document.getElementById('gov-content');
    govContent.classList.remove('hidden');
    govContent.innerHTML = `
      <div class="error-banner">
        <span class="error-banner-text">Failed to load compliance data: ${escapeHtml(err.message)}</span>
        <button class="btn btn-ghost btn-sm" onclick="loadGovernance()">Retry</button>
      </div>
    `;
  }
}

window.renderGovernance = renderGovernance;
