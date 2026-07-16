/**
 * Sentinel Trace Visualization
 */
function renderTraceTimeline(traceData) {
  if (!traceData) return '<div class="text-muted">No trace data available.</div>';

  const steps = traceData.steps || traceData.events || traceData.trace || [];
  const assertions = traceData.assertions || traceData.results || [];
  const stateChanges = traceData.state_changes || traceData.state || [];

  // Calculate max duration for bar scaling (log scale)
  let maxDuration = 1;
  for (const step of steps) {
    const dur = step.duration || step.duration_ms / 1000 || 0;
    if (dur > maxDuration) maxDuration = dur;
  }

  const barScale = (dur) => {
    if (dur <= 0) return 2;
    // Log scale: maps to 5%–100% width
    const logMax = Math.log(maxDuration + 1);
    const logVal = Math.log(dur + 1);
    return Math.max(5, Math.min(100, (logVal / logMax) * 100));
  };

  const stepTypeClass = (step) => {
    const type = (step.type || step.action || '').toLowerCase();
    if (type.includes('tool_call') || type.includes('toolcall') || type === 'tool') return 'tool_call';
    if (type.includes('error') || type.includes('fail')) return 'fail';
    if (type.includes('reason') || type.includes('thought')) return 'reasoning';
    if (type.includes('plan')) return 'plan';
    return 'pass';
  };

  const stepIcon = (step) => {
    const cls = stepTypeClass(step);
    const icons = {
      pass: '✓',
      fail: '✗',
      tool_call: '⚡',
      reasoning: '💭',
      plan: '📋',
    };
    return icons[cls] || '•';
  };

  let html = '<div class="trace-container">';

  // Steps timeline
  if (steps.length > 0) {
    html += '<div class="trace-timeline">';
    for (const step of steps) {
      const cls = stepTypeClass(step);
      const dur = step.duration || (step.duration_ms ? step.duration_ms / 1000 : 0);
      const pct = barScale(dur);
      const toolName = step.tool || step.tool_name || step.name || step.type || 'step';
      const error = step.error || step.error_message;

      html += `
        <div class="trace-step">
          <div class="trace-step-icon ${cls}"></div>
          <div class="trace-step-content">
            <div class="trace-step-header">
              <span class="trace-step-tool">${escapeHtml(toolName)}</span>
              ${dur > 0 ? `<span class="trace-step-duration">${formatDuration(dur)}</span>` : ''}
              <span class="badge badge-${cls === 'pass' ? 'pass' : cls === 'fail' ? 'fail' : cls === 'tool_call' ? 'accent' : 'neutral'}" style="font-size:0.65rem;">${stepIcon(step)} ${escapeHtml(cls.replace('_', ' '))}</span>
            </div>
            <div class="trace-step-bar">
              <div class="trace-step-bar-fill ${cls}" style="width:${pct}%"></div>
            </div>
            ${step.content || step.output ? `
              <div class="text-xs text-muted mt-sm" style="max-height:3rem; overflow:hidden; white-space:pre-wrap;">${escapeHtml(String(step.content || step.output).substring(0, 200))}</div>
            ` : ''}
            ${error ? `<div class="trace-step-error">${escapeHtml(String(error))}</div>` : ''}
          </div>
        </div>
      `;
    }
    html += '</div>';
  } else {
    html += `
      <div class="empty-state">
        <div class="empty-state-icon">🔍</div>
        <div class="empty-state-title">No trace steps</div>
        <div class="empty-state-text">Trace data will appear here during execution.</div>
      </div>
    `;
  }

  // Assertions
  if (assertions.length > 0) {
    html += `
      <div class="trace-assertions">
        <h3>Assertions (${assertions.filter(a => a.passed !== false && a.result !== false && a.status !== 'failed').length}/${assertions.length} passed)</h3>
        ${assertions.map(a => {
          const passed = a.passed !== false && a.result !== false && a.status !== 'failed';
          return `
            <div class="assertion-item">
              <span class="assertion-icon ${passed ? 'text-pass' : 'text-fail'}">${passed ? '✓' : '✗'}</span>
              <span class="assertion-text text-sm">${escapeHtml(a.description || a.name || a.expression || JSON.stringify(a))}</span>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  // State changes
  if (stateChanges.length > 0) {
    html += `
      <div class="trace-state">
        <h3>State Changes</h3>
        ${stateChanges.map(sc => `
          <div class="state-item">
            <span class="state-key">${escapeHtml(sc.key || sc.name || sc.field || '')}:</span>
            <span class="state-value">${escapeHtml(String(sc.value || sc.new_value || sc.after || ''))}</span>
          </div>
        `).join('')}
      </div>
    `;
  }

  html += '</div>';
  return html;
}

window.renderTraceTimeline = renderTraceTimeline;
