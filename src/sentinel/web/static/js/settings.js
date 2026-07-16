/**
 * Sentinel WebUI — Settings Page
 *
 * Manages model endpoint configuration and general settings.
 */
(async function () {
  "use strict";

  const { escapeHtml, showToast } = window.SentinelApp || {};

  /**
   * Render the settings page.
   */
  window.renderSettings = async function (container) {
    container.innerHTML = `
      <div class="page-header">
        <h1>Settings</h1>
      </div>

      <div class="card">
        <h2 class="card-title">Model Endpoints</h2>
        <p class="text-muted">Configure LLM providers for test runs.</p>
        <div id="endpoints-list" class="mt-1">
          <div class="loading-spinner"></div>
        </div>
        <button class="btn btn-primary mt-1" id="add-endpoint-btn">
          + Add Endpoint
        </button>
      </div>

      <div class="card mt-1">
        <h2 class="card-title">General</h2>
        <div class="form-group">
          <label class="form-label">Default Scenario Directory</label>
          <input type="text" class="form-input" id="scenario-dir" value="examples" />
        </div>
        <div class="form-group">
          <label class="form-label">Auto-save Run Results</label>
          <input type="checkbox" class="form-checkbox" id="auto-save" checked />
        </div>
        <button class="btn btn-primary mt-1" id="save-settings-btn">
          Save Settings
        </button>
      </div>

      <div id="endpoint-modal" class="modal hidden">
        <div class="modal-content">
          <div class="modal-header">
            <h3>Add Model Endpoint</h3>
            <button class="btn btn-ghost modal-close">&times;</button>
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label class="form-label">Provider</label>
              <select class="form-select" id="ep-provider">
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="openai_compatible">OpenAI-Compatible (Local)</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Model</label>
              <input type="text" class="form-input" id="ep-model" placeholder="gpt-4" />
            </div>
            <div class="form-group">
              <label class="form-label">Base URL (for local/compatible)</label>
              <input type="text" class="form-input" id="ep-base-url" placeholder="http://localhost:11434/v1" />
            </div>
            <div class="form-group">
              <label class="form-label">API Key Environment Variable</label>
              <input type="text" class="form-input" id="ep-api-key-env" placeholder="OPENAI_API_KEY" />
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost modal-close">Cancel</button>
            <button class="btn btn-primary" id="save-endpoint-btn">Save</button>
          </div>
        </div>
      </div>
    `;

    // Wire up events
    document.getElementById("add-endpoint-btn")?.addEventListener("click", () => {
      document.getElementById("endpoint-modal")?.classList.remove("hidden");
    });

    document.querySelectorAll(".modal-close").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".modal").forEach((m) => m.classList.add("hidden"));
      });
    });

    document.getElementById("save-settings-btn")?.addEventListener("click", () => {
      showToast("Settings saved (local only)", "success");
    });

    document.getElementById("save-endpoint-btn")?.addEventListener("click", () => {
      document.querySelectorAll(".modal").forEach((m) => m.classList.add("hidden"));
      showToast("Endpoint saved", "success");
    });

    // Load endpoints
    await loadEndpoints();
  };

  async function loadEndpoints() {
    const listEl = document.getElementById("endpoints-list");
    if (!listEl) return;

    // For now, show a placeholder. Real endpoint storage comes in Phase 7.4.
    listEl.innerHTML = `
      <div class="empty-state-sm">
        <p class="text-muted">No model endpoints configured.</p>
        <p class="text-muted text-sm">
          Add an endpoint to route test runs at different LLMs.
        </p>
      </div>
    `;
  }
})();
