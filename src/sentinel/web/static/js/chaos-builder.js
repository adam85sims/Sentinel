/**
 * Sentinel Chaos Configuration Builder
 *
 * Interactive UI for composing chaos injection configurations
 * with live YAML preview, preset loading, and injector controls.
 */
function renderChaosBuilder() {
  const content = document.getElementById('app-content');
  content.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">
        <svg width="24" height="24" viewBox="0 0 16 16" fill="currentColor">
          <path d="M8 0a8 8 0 100 16A8 8 0 008 0zm1 12H7v-2h2v2zm0-4H7V3h2v5z" opacity=".7"/>
        </svg>
        Chaos Configuration Builder
      </h1>
      <p class="page-subtitle">Design chaos experiments by configuring injectors and budgets</p>
    </div>

    <!-- Top controls row -->
    <div class="flex items-center gap-md mb-lg" style="flex-wrap:wrap;">
      <div class="form-group" style="margin:0; flex:1; min-width:200px;">
        <label class="form-label" for="chaos-preset-select">Preset</label>
        <select class="form-select" id="chaos-preset-select">
          <option value="">-- Select a preset --</option>
        </select>
      </div>
      <div class="form-group" style="margin:0; min-width:180px;">
        <label class="form-label" for="chaos-budget-input">Max Failures Per Run</label>
        <input type="number" class="form-input" id="chaos-budget-input"
               min="0" max="100" value="3" placeholder="Budget" />
      </div>
    </div>

    <!-- Injectors container -->
    <div id="chaos-injectors-loading" class="loading-placeholder">
      <div class="spinner"></div>
      <p>Loading injectors…</p>
    </div>
    <div id="chaos-injectors-container" class="hidden"></div>

    <!-- YAML Preview -->
    <div class="section-header mt-lg">
      <h2 class="section-title">Generated YAML</h2>
    </div>
    <div class="yaml-preview-box" id="chaos-yaml-preview">
      <span style="color:var(--fg-subtle); font-style:italic;">
        Configure injectors above to generate YAML…
      </span>
    </div>

    <!-- Action buttons -->
    <div class="flex items-center gap-sm mt-lg" style="flex-wrap:wrap;">
      <button class="btn btn-primary" id="chaos-apply-btn">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
          <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z"/>
        </svg>
        Apply to Scenario
      </button>
      <button class="btn btn-ghost" id="chaos-export-btn">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
          <path d="M3.5 13h9a.75.75 0 010 1.5h-9a.75.75 0 010-1.5zM8 1a.75.75 0 01.75.75v7.59l2.22-2.22a.75.75 0 111.06 1.06l-3.5 3.5a.75.75 0 01-1.06 0l-3.5-3.5a.75.75 0 111.06-1.06l2.22 2.22V1.75A.75.75 0 018 1z"/>
        </svg>
        Export YAML
      </button>
    </div>
  `;

  // Bind action buttons
  document.getElementById('chaos-apply-btn').addEventListener('click', _applyToScenario);
  document.getElementById('chaos-export-btn').addEventListener('click', _exportYaml);

  // Bind budget input
  document.getElementById('chaos-budget-input').addEventListener('input', _onControlChange);

  // Bind preset selector
  document.getElementById('chaos-preset-select').addEventListener('change', _onPresetChange);

  // Load data from API
  _loadChaosData();
}

// ── Helpers ──
// showToast lives on SentinelApp, not window — alias it locally (same pattern as editor.js / settings.js)
const _showToast = (msg, type) => (window.SentinelApp?.showToast || console.log)(msg, type);

// ── State ──
let _chaosInjectors = [];
let _chaosPresets = [];
let _chaosYamlCache = '';
let _previewDebounce = null;

/**
 * Fetch injectors and presets from the API on load.
 */
async function _loadChaosData() {
  try {
    const [injectorsData, presetsData] = await Promise.all([
      SentinelAPI.getChaosInjectors(),
      SentinelAPI.getChaosPresets()
    ]);

    _chaosInjectors = injectorsData.injectors || [];
    _chaosPresets = presetsData.presets || [];

    _renderPresets();
    _renderInjectors();

    document.getElementById('chaos-injectors-loading').classList.add('hidden');
    document.getElementById('chaos-injectors-container').classList.remove('hidden');
  } catch (err) {
    document.getElementById('chaos-injectors-loading').innerHTML = `
      <div class="error-banner">
        <span class="error-banner-text">Failed to load chaos data: ${escapeHtml(err.message)}</span>
        <button class="btn btn-ghost btn-sm" onclick="renderChaosBuilder()">Retry</button>
      </div>
    `;
  }
}

/**
 * Populate the preset dropdown.
 */
function _renderPresets() {
  const select = document.getElementById('chaos-preset-select');
  if (!select) return;

  _chaosPresets.forEach((preset, idx) => {
    const name = preset.name || preset.label || `Preset ${idx + 1}`;
    const opt = document.createElement('option');
    opt.value = String(idx);
    opt.textContent = name;
    if (preset.description) {
      opt.title = preset.description;
    }
    select.appendChild(opt);
  });
}

/**
 * Render injector sections for each known injector type.
 */
function _renderInjectors() {
  const container = document.getElementById('chaos-injectors-container');
  if (!container) return;

  if (_chaosInjectors.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">💉</div>
        <div class="empty-state-title">No injectors available</div>
        <div class="empty-state-text">No chaos injectors were returned by the API.</div>
      </div>
    `;
    return;
  }

  container.innerHTML = _chaosInjectors.map((inj, idx) =>
    _renderInjectorSection(inj, idx)
  ).join('');

  // Attach change listeners to all controls within injector sections
  container.querySelectorAll('input, select').forEach(el => {
    el.addEventListener('input', _onControlChange);
    el.addEventListener('change', _onControlChange);
  });

  // Attach toggle listeners for checkboxes
  container.querySelectorAll('.chaos-section-header input[type="checkbox"]').forEach(cb => {
    cb.addEventListener('change', _onControlChange);
  });
}

/**
 * Render a single injector section with its parameters.
 */
function _renderInjectorSection(injector, idx) {
  const id = injector.id || injector.name || `injector-${idx}`;
  const name = injector.display_name || injector.name || injector.id || `Injector ${idx}`;
  const description = injector.description || '';
  const enabled = injector.default_enabled !== false;
  const params = injector.parameters || injector.params || [];

  const paramsHtml = params.length > 0
    ? `<div class="chaos-section-body">${params.map(p => _renderParamControl(p, id)).join('')}</div>`
    : `<div class="chaos-section-body" style="color:var(--fg-subtle); font-size:0.82rem; font-style:italic;">
        No configurable parameters.
       </div>`;

  return `
    <div class="chaos-section" id="chaos-section-${escapeHtml(id)}">
      <div class="chaos-section-header">
        <input type="checkbox" id="chaos-enable-${escapeHtml(id)}"
               data-injector="${escapeHtml(id)}"
               ${enabled ? 'checked' : ''} />
        <label for="chaos-enable-${escapeHtml(id)}" style="cursor:pointer; font-weight:600;">
          ${escapeHtml(name)}
        </label>
        ${description ? `<span style="color:var(--fg-subtle); font-size:0.8rem; margin-left:0.5rem;">${escapeHtml(description)}</span>` : ''}
      </div>
      ${paramsHtml}
    </div>
  `;
}

/**
 * Render a parameter control based on its type.
 */
function _renderParamControl(param, injectorId) {
  const name = param.name || param.id || '';
  const label = param.label || param.display_name || name;
  const type = (param.type || 'string').toLowerCase();
  const paramName = `chaos-param-${injectorId}-${name}`;

  switch (type) {
    case 'range':
      return _renderRangeParam(param, paramName, injectorId, label);
    case 'select':
      return _renderSelectParam(param, paramName, injectorId, label);
    case 'number':
      return _renderNumberParam(param, paramName, injectorId, label);
    case 'string':
    default:
      return _renderStringParam(param, paramName, injectorId, label);
  }
}

/**
 * Render a range (slider) parameter with a live value label.
 */
function _renderRangeParam(param, paramName, injectorId, label) {
  const min = param.min !== undefined ? param.min : 0;
  const max = param.max !== undefined ? param.max : 100;
  const step = param.step !== undefined ? param.step : 1;
  const value = param.default !== undefined ? param.default : Math.round((Number(min) + Number(max)) / 2);

  return `
    <div class="chaos-slider-row">
      <label for="${escapeHtml(paramName)}">${escapeHtml(label)}</label>
      <input type="range" id="${escapeHtml(paramName)}"
             data-injector="${escapeHtml(injectorId)}"
             data-param="${escapeHtml(param.name || param.id || '')}"
             min="${escapeHtml(String(min))}" max="${escapeHtml(String(max))}"
             step="${escapeHtml(String(step))}"
             value="${escapeHtml(String(value))}" />
      <span class="slider-value" id="${escapeHtml(paramName)}-val">${escapeHtml(String(value))}</span>
    </div>
  `;
}

/**
 * Render a select (dropdown) parameter.
 */
function _renderSelectParam(param, paramName, injectorId, label) {
  const options = param.options || param.choices || [];
  const defaultValue = param.default !== undefined ? String(param.default) : '';

  const optionsHtml = options.map(opt => {
    const optValue = typeof opt === 'object' ? (opt.value || opt.id || '') : String(opt);
    const optLabel = typeof opt === 'object' ? (opt.label || opt.display_name || optValue) : String(opt);
    const selected = String(optValue) === defaultValue ? ' selected' : '';
    return `<option value="${escapeHtml(optValue)}"${selected}>${escapeHtml(optLabel)}</option>`;
  }).join('');

  return `
    <div class="form-group">
      <label class="form-label" for="${escapeHtml(paramName)}">${escapeHtml(label)}</label>
      <select class="form-select" id="${escapeHtml(paramName)}"
              data-injector="${escapeHtml(injectorId)}"
              data-param="${escapeHtml(param.name || param.id || '')}">
        ${optionsHtml}
      </select>
    </div>
  `;
}

/**
 * Render a number input parameter.
 */
function _renderNumberParam(param, paramName, injectorId, label) {
  const min = param.min !== undefined ? param.min : '';
  const max = param.max !== undefined ? param.max : '';
  const step = param.step !== undefined ? param.step : 1;
  const value = param.default !== undefined ? param.default : '';

  return `
    <div class="form-group">
      <label class="form-label" for="${escapeHtml(paramName)}">${escapeHtml(label)}</label>
      <input type="number" class="form-input" id="${escapeHtml(paramName)}"
             data-injector="${escapeHtml(injectorId)}"
             data-param="${escapeHtml(param.name || param.id || '')}"
             ${min !== '' ? `min="${escapeHtml(String(min))}"` : ''}
             ${max !== '' ? `max="${escapeHtml(String(max))}"` : ''}
             step="${escapeHtml(String(step))}"
             value="${escapeHtml(String(value))}" />
    </div>
  `;
}

/**
 * Render a string (text) input parameter.
 */
function _renderStringParam(param, paramName, injectorId, label) {
  const value = param.default !== undefined ? String(param.default) : '';
  const placeholder = param.placeholder || '';

  return `
    <div class="form-group">
      <label class="form-label" for="${escapeHtml(paramName)}">${escapeHtml(label)}</label>
      <input type="text" class="form-input" id="${escapeHtml(paramName)}"
             data-injector="${escapeHtml(injectorId)}"
             data-param="${escapeHtml(param.name || param.id || '')}"
             value="${escapeHtml(value)}"
             ${placeholder ? `placeholder="${escapeHtml(placeholder)}"` : ''} />
    </div>
  `;
}

// ── Control event handlers ──

/**
 * Called when any injector control changes. Debounces the YAML preview update.
 */
function _onControlChange(e) {
  // Update slider value labels in real-time
  if (e && e.target && e.target.type === 'range') {
    const valLabel = document.getElementById(e.target.id + '-val');
    if (valLabel) {
      valLabel.textContent = e.target.value;
    }
  }

  // Debounce the preview update (300ms)
  if (_previewDebounce) clearTimeout(_previewDebounce);
  _previewDebounce = setTimeout(_updateYamlPreview, 300);
}

/**
 * Called when a preset is selected. Applies preset config to the form controls.
 */
function _onPresetChange() {
  const select = document.getElementById('chaos-preset-select');
  const idx = parseInt(select.value, 10);
  if (isNaN(idx) || idx < 0 || idx >= _chaosPresets.length) return;

  const preset = _chaosPresets[idx];

  // Apply budget if present
  if (preset.budget_max_failures !== undefined) {
    const budgetInput = document.getElementById('chaos-budget-input');
    if (budgetInput) budgetInput.value = String(preset.budget_max_failures);
  }

  // Apply injector settings from the preset
  const injectorConfig = preset.injectors || preset.config || {};
  _applyInjectorConfig(injectorConfig);

  // Trigger YAML preview
  _onControlChange({ target: { type: 'text' } });
}

/**
 * Apply a preset's injector configuration to the form controls.
 */
function _applyInjectorConfig(config) {
  const container = document.getElementById('chaos-injectors-container');
  if (!container) return;

  // Enable/disable injectors and set their parameter values
  for (const [injectorId, injConfig] of Object.entries(config)) {
    const enabled = injConfig !== false && injConfig !== null;
    const checkbox = document.getElementById(`chaos-enable-${injectorId}`);
    if (checkbox) checkbox.checked = !!enabled;

    if (typeof injConfig !== 'object' || injConfig === null) continue;

    // Set parameter values from the config object
    const params = injConfig.params || injConfig.parameters || injConfig;
    if (typeof params !== 'object') continue;

    for (const [paramName, paramValue] of Object.entries(params)) {
      if (paramName === 'params' || paramName === 'parameters') continue;
      const el = document.getElementById(`chaos-param-${injectorId}-${paramName}`);
      if (el) {
        el.value = String(paramValue);
        // Update slider labels
        const valLabel = document.getElementById(el.id + '-val');
        if (valLabel) valLabel.textContent = String(paramValue);
      }
    }
  }
}

// ── YAML Preview ──

/**
 * Collect current form state and request a YAML preview from the API.
 */
async function _updateYamlPreview() {
  const previewBox = document.getElementById('chaos-yaml-preview');
  if (!previewBox) return;

  const config = _collectFormState();

  // Show a subtle loading indicator
  previewBox.style.opacity = '0.5';

  try {
    const result = await SentinelAPI.previewChaosConfig(config);
    _chaosYamlCache = result.yaml || '';
    const injectorCount = result.injector_count || 0;

    previewBox.style.opacity = '1';

    if (_chaosYamlCache) {
      previewBox.innerHTML = `<code>${escapeHtml(_chaosYamlCache)}</code>`;
    } else {
      previewBox.innerHTML = `
        <span style="color:var(--fg-subtle); font-style:italic;">
          No YAML generated. Enable at least one injector.
        </span>
      `;
    }

    appendToLog({
      level: 'info',
      message: `Chaos preview updated: ${injectorCount} injector(s) active`
    });
  } catch (err) {
    previewBox.style.opacity = '1';
    previewBox.innerHTML = `
      <span style="color:var(--fail);">
        Preview error: ${escapeHtml(err.message)}
      </span>
    `;
    appendToLog({
      level: 'error',
      message: `Chaos preview failed: ${err.message}`
    });
  }
}

/**
 * Collect all form state into the payload expected by the chaos API.
 */
function _collectFormState() {
  const budgetInput = document.getElementById('chaos-budget-input');
  const budgetMaxFailures = budgetInput ? parseInt(budgetInput.value, 10) || 3 : 3;

  const injectors = {};

  _chaosInjectors.forEach(inj => {
    const id = inj.id || inj.name || '';
    const checkbox = document.getElementById(`chaos-enable-${id}`);
    if (!checkbox || !checkbox.checked) return;

    const injConfig = {};
    const params = inj.parameters || inj.params || [];

    params.forEach(param => {
      const paramName = param.name || param.id || '';
      const el = document.getElementById(`chaos-param-${id}-${paramName}`);
      if (!el) return;

      const type = (param.type || 'string').toLowerCase();
      let value = el.value;

      if (type === 'range' || type === 'number') {
        value = Number(value);
        if (isNaN(value)) {
          const defaultVal = param.default !== undefined ? Number(param.default) : 0;
          value = defaultVal;
        }
      }

      injConfig[paramName] = value;
    });

    injectors[id] = injConfig;
  });

  return {
    injectors,
    budget_max_failures: budgetMaxFailures
  };
}

// ── Action Buttons ──

/**
 * Navigate to the scenario page to apply the chaos config.
 */
function _applyToScenario() {
  const config = _collectFormState();
  const injectorCount = Object.keys(config.injectors).length;

  if (injectorCount === 0) {
    _showToast('Enable at least one injector before applying', 'warn');
    return;
  }

  appendToLog({
    level: 'info',
    message: `Applying chaos config with ${injectorCount} injector(s) to scenario`
  });

  // Store the config in sessionStorage so the scenario page can pick it up
  try {
    sessionStorage.setItem('sentinel-chaos-config', JSON.stringify(config));
  } catch (_) { /* storage unavailable */ }

  _showToast('Chaos config ready — select a scenario to apply', 'success');
  SentinelApp.navigate('#/scenarios');
}

/**
 * Export the current chaos YAML to clipboard (or download as file fallback).
 */
function _exportYaml() {
  if (!_chaosYamlCache) {
    _showToast('No YAML to export — configure at least one injector', 'warn');
    return;
  }

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(_chaosYamlCache).then(() => {
      _showToast('YAML copied to clipboard', 'success');
      appendToLog({ level: 'success', message: 'Chaos YAML copied to clipboard' });
    }).catch(() => {
      _downloadYaml();
    });
  } else {
    _downloadYaml();
  }
}

/**
 * Download the YAML as a .yaml file (fallback for clipboard API).
 */
function _downloadYaml() {
  const blob = new Blob([_chaosYamlCache], { type: 'text/yaml' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'chaos-config.yaml';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);

  _showToast('YAML downloaded as chaos-config.yaml', 'success');
  appendToLog({ level: 'success', message: 'Chaos YAML downloaded' });
}

// ── Global Registration ──
window.renderChaosBuilder = renderChaosBuilder;
