/**
 * Sentinel WebUI — Settings Page
 *
 * Manages model endpoint configuration and general settings.
 */
(async function () {
  "use strict";

  // Retrieve escapeHtml and showToast lazily because window.SentinelApp is defined in app.js (loaded after settings.js)
  const getAppUtils = () => window.SentinelApp || {};
  const escapeHtml = (text) => (getAppUtils().escapeHtml || (x => x))(text);
  const showToast = (msg, type) => (getAppUtils().showToast || console.log)(msg, type);

  /**
   * Render the settings page.
   */
  window.renderSettings = async function () {
    const container = document.getElementById("app-content");
    if (!container) return;
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
                <option value="lm_studio">LM Studio</option>
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
      // Clear inputs
      const epModel = document.getElementById("ep-model");
      const epBaseUrl = document.getElementById("ep-base-url");
      const epApiKeyEnv = document.getElementById("ep-api-key-env");
      if (epModel) epModel.value = "";
      if (epBaseUrl) epBaseUrl.value = "";
      if (epApiKeyEnv) epApiKeyEnv.value = "";
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

    document.getElementById("save-endpoint-btn")?.addEventListener("click", async () => {
      const provider = document.getElementById("ep-provider")?.value;
      const model = document.getElementById("ep-model")?.value;
      const base_url = document.getElementById("ep-base-url")?.value;
      const api_key_env = document.getElementById("ep-api-key-env")?.value;

      if (!model) {
        showToast("Model name is required", "error");
        return;
      }

      try {
        await SentinelAPI.addModelEndpoint({
          provider,
          model,
          base_url: base_url || null,
          api_key_env: api_key_env || null
        });
        document.querySelectorAll(".modal").forEach((m) => m.classList.add("hidden"));
        showToast("Endpoint saved", "success");
        await loadEndpoints();
      } catch (err) {
        showToast(`Failed to save endpoint: ${err.message}`, "error");
      }
    });

    // Load endpoints
    await loadEndpoints();
  };

  async function loadEndpoints() {
    const listEl = document.getElementById("endpoints-list");
    if (!listEl) return;

    try {
      const data = await SentinelAPI.getModelEndpoints();
      const endpoints = data.endpoints || [];

      if (endpoints.length === 0) {
        listEl.innerHTML = `
          <div class="empty-state-sm">
            <p class="text-muted">No model endpoints configured.</p>
            <p class="text-muted text-sm">
              Add an endpoint to route test runs at different LLMs.
            </p>
          </div>
        `;
        return;
      }

      listEl.innerHTML = endpoints.map(ep => `
        <div class="endpoint-card" data-id="${escapeHtml(ep.id)}">
          <div class="endpoint-info">
            <span class="endpoint-provider">${escapeHtml(ep.provider.toUpperCase().replace('_', ' '))}</span>
            <span class="endpoint-model">${escapeHtml(ep.model)}</span>
            ${ep.base_url ? `<span class="text-muted text-sm" style="margin-left: 0.5rem;">(${escapeHtml(ep.base_url)})</span>` : ''}
          </div>
          <div class="endpoint-actions">
            <button class="btn btn-sm btn-secondary test-endpoint-btn" data-id="${escapeHtml(ep.id)}">Test</button>
            <button class="btn btn-sm btn-danger delete-endpoint-btn" data-id="${escapeHtml(ep.id)}">Delete</button>
          </div>
        </div>
      `).join('');

      // Wire up test buttons
      listEl.querySelectorAll(".test-endpoint-btn").forEach(btn => {
        btn.addEventListener("click", async (e) => {
          const id = e.target.getAttribute("data-id");
          e.target.disabled = true;
          e.target.innerText = "Testing...";
          try {
            const res = await SentinelAPI.testModelEndpoint(id);
            if (res.success) {
              showToast(res.message, "success");
            } else {
              showToast(res.message, "error");
            }
          } catch (err) {
            showToast(`Test failed: ${err.message}`, "error");
          } finally {
            e.target.disabled = false;
            e.target.innerText = "Test";
          }
        });
      });

      // Wire up delete buttons
      listEl.querySelectorAll(".delete-endpoint-btn").forEach(btn => {
        btn.addEventListener("click", async (e) => {
          const id = e.target.getAttribute("data-id");
          if (confirm("Are you sure you want to delete this endpoint?")) {
            try {
              await SentinelAPI.deleteModelEndpoint(id);
              showToast("Endpoint deleted", "success");
              await loadEndpoints();
            } catch (err) {
              showToast(`Failed to delete: ${err.message}`, "error");
            }
          }
        });
      });

    } catch (err) {
      listEl.innerHTML = `<p class="text-danger">Failed to load endpoints: ${escapeHtml(err.message)}</p>`;
    }
  }
})();
