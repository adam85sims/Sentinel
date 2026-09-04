/**
 * Sentinel Trace Visualization — Waterfall View
 *
 * Renders a Gantt-style waterfall timeline of agent execution steps,
 * with assertion results and state changes.
 */
function renderTraceTimeline(traceData) {
  if (!traceData) return '<div class="text-muted">No trace data available.</div>';

  const steps = traceData.steps || traceData.events || traceData.trace || [];
  const assertions = traceData.assertions || traceData.results || [];
  const stateChanges = traceData.state_changes || traceData.state || [];

  if (steps.length === 0) {
    return `
      <div class="empty-state">
        <div class="empty-state-icon">🔍</div>
        <div class="empty-state-title">No trace steps</div>
        <div class="empty-state-text">Trace data will appear here during execution.</div>
      </div>
    `;
  }

  // Calculate timing for waterfall positioning
  let totalDuration = 0;
  const stepData = steps.map((step, i) => {
    const dur = step.duration || (step.duration_ms ? step.duration_ms / 1000 : 0);
    const start = step.start_time || totalDuration;
    totalDuration += dur;
    const type = (step.type || step.action || '').toLowerCase();
    const isTool = type.includes('tool_call') || type.includes('toolcall') || type === 'tool';
    const isError = type.includes('error') || type.includes('fail') || step.error;
    const isReasoning = type.includes('reason') || type.includes('thought');
    const name = step.tool || step.tool_name || step.name || step.type || `step ${i + 1}`;

    return {
      ...step,
      index: i,
      dur,
      start,
      type: isTool ? 'tool_call' : isError ? 'fail' : isReasoning ? 'reasoning' : 'pass',
      name,
      error: step.error || step.error_message,
    };
  });

  const maxDur = Math.max(totalDuration, 0.001);

  // Build waterfall HTML
  const waterfallBars = stepData.map(s => {
    const leftPct = maxDur > 0 ? (s.start / maxDur) * 100 : 0;
    const widthPct = maxDur > 0 ? Math.max(2, (s.dur / maxDur) * 100) : 2;

    const typeColors = {
      tool_call: 'var(--accent)',
      fail: 'var(--fail)',
      reasoning: 'var(--fg-subtle)',
      pass: 'var(--pass)',
    };
    const color = typeColors[s.type] || 'var(--fg-muted)';

    const icons = { tool_call: '⚡', fail: '✗', reasoning: '💭', pass: '✓' };
    const icon = icons[s.type] || '•';

    return `
      <div class="trace-step" style="position:relative; height:28px; margin-bottom:2px;">
        <div style="position:absolute; left:0; top:0; width:120px; height:100%; display:flex; align-items:center; gap:4px; font-size:0.75rem; color:var(--fg-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
          <span style="color:${color};">${icon}</span>
          <span>${escapeHtml(s.name)}</span>
        </div>
        <div style="position:absolute; left:120px; right:0; top:4px; height:20px;">
          <div style="position:absolute; left:${leftPct}%; width:${Math.max(1, widthPct)}%; height:100%; background:${color}; opacity:0.7; border-radius:3px; min-width:4px;" title="${escapeHtml(s.name)}: ${formatDuration(s.dur)}"></div>
        </div>
        <div style="position:absolute; right:0; top:0; height:100%; display:flex; align-items:center; font-size:0.7rem; font-family:var(--font-mono); color:var(--fg-subtle);">
          ${s.dur > 0 ? formatDuration(s.dur) : ''}
        </div>
      </div>
    `;
  }).join('');

  // Time axis
  const timeAxis = `
    <div style="position:relative; height:20px; margin-bottom:4px; border-bottom:1px solid var(--border-light);">
      <div style="position:absolute; left:120px; right:0; top:0; height:100%;">
        ${[0, 25, 50, 75, 100].map(pct => `
          <span style="position:absolute; left:${pct}%; top:0; font-size:0.65rem; color:var(--fg-subtle); font-family:var(--font-mono); transform:translateX(-50%);">
            ${formatDuration(maxDur * pct / 100)}
          </span>
        `).join('')}
      </div>
    </div>
  `;

  let html = '<div class="trace-container">';

  // Waterfall
  html += `
    <div class="trace-waterfall" style="padding:0.5rem;">
      ${timeAxis}
      ${waterfallBars}
    </div>
  `;

  // Step details (collapsible)
  html += '<div class="trace-details" style="margin-top:1rem;">';
  html += '<h3 style="font-size:0.85rem; color:var(--fg-muted); margin-bottom:0.5rem;">Step Details</h3>';
  for (const s of stepData) {
    const color = s.type === 'fail' ? 'var(--fail)' : s.type === 'tool_call' ? 'var(--accent)' : 'var(--pass)';
    html += `
      <div style="padding:0.4rem 0; border-bottom:1px solid var(--border-light); font-size:0.8rem;">
        <span style="color:${color}; font-weight:600;">${escapeHtml(s.name)}</span>
        <span style="color:var(--fg-subtle); margin-left:0.5rem;">${formatDuration(s.dur)}</span>
        ${s.error ? `<span style="color:var(--fail); margin-left:0.5rem;">${escapeHtml(String(s.error))}</span>` : ''}
        ${s.output ? `<div style="color:var(--fg-subtle); margin-top:0.25rem; max-height:3rem; overflow:hidden; white-space:pre-wrap; font-family:var(--font-mono); font-size:0.75rem;">${escapeHtml(String(s.output).substring(0, 200))}</div>` : ''}
      </div>
    `;
  }
  html += '</div>';

  // Assertions
  if (assertions.length > 0) {
    const passed = assertions.filter(a => a.passed !== false && a.result !== false && a.status !== 'failed').length;
    html += `
      <div class="trace-assertions" style="margin-top:1rem;">
        <h3 style="font-size:0.85rem; color:var(--fg-muted); margin-bottom:0.5rem;">Assertions (${passed}/${assertions.length} passed)</h3>
        ${assertions.map(a => {
          const ok = a.passed !== false && a.result !== false && a.status !== 'failed';
          return `
            <div class="assertion-item" style="display:flex; gap:0.4rem; padding:0.3rem 0; font-size:0.8rem;">
              <span style="color:${ok ? 'var(--pass)' : 'var(--fail)'};">${ok ? '✓' : '✗'}</span>
              <span>${escapeHtml(a.description || a.name || a.expression || JSON.stringify(a))}</span>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  // State changes
  if (stateChanges.length > 0) {
    html += `
      <div class="trace-state" style="margin-top:1rem;">
        <h3 style="font-size:0.85rem; color:var(--fg-muted); margin-bottom:0.5rem;">State Changes</h3>
        ${stateChanges.map(sc => `
          <div style="display:flex; gap:0.4rem; padding:0.3rem 0; font-size:0.8rem; font-family:var(--font-mono);">
            <span style="color:var(--accent);">${escapeHtml(sc.key || sc.name || sc.field || '')}</span>
            <span style="color:var(--fg-subtle);">→</span>
            <span>${escapeHtml(String(sc.value || sc.new_value || sc.after || ''))}</span>
          </div>
        `).join('')}
      </div>
    `;
  }

  html += '</div>';
  return html;
}

window.renderTraceTimeline = renderTraceTimeline;
