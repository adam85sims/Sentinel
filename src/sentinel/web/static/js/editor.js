/**
 * Sentinel Scenario Editor
 *
 * Split-view editor: YAML textarea on the left, live preview on the right.
 * Supports creating new scenarios and editing existing ones.
 */
(function () {
  "use strict";

  const escapeHtml = (text) => (window.SentinelApp?.escapeHtml || (x => x))(text);
  const showToast = (msg, type) => (window.SentinelApp?.showToast || console.log)(msg, type);

  /**
   * Render the scenario editor page for a specific scenario.
   * If id === '__new__', creates a new blank scenario.
   */
  window.renderScenarioEditor = async function (id) {
    const container = document.getElementById("app-content");
    if (!container) return;

    const isNew = id === "__new__";
    let originalContent = "";

    if (!isNew) {
      container.innerHTML = `
        <div class="page-header">
          <div class="flex items-center gap-md">
            <a href="#/scenarios" class="btn btn-ghost btn-sm">← Back</a>
            <h1 class="page-title">Loading…</h1>
          </div>
        </div>
        <div class="loading-placeholder"><div class="spinner"></div></div>
      `;
      try {
        const s = await SentinelAPI.getScenario(id);
        originalContent = s.raw_yaml || s.yaml || _scenarioToYaml(s);
      } catch (err) {
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-icon">⚠</div>
            <h3>Failed to load scenario</h3>
            <p>${escapeHtml(err.message)}</p>
            <a href="#/scenarios" class="btn btn-primary">Back to Scenarios</a>
          </div>
        `;
        return;
      }
    } else {
      originalContent = _blankScenarioYaml();
    }

    const title = isNew ? "New Scenario" : `Edit: ${id}`;

    container.innerHTML = `
      <div class="page-header">
        <div class="flex items-center gap-md">
          <a href="#/scenarios" class="btn btn-ghost btn-sm">← Back</a>
          <h1 class="page-title">${escapeHtml(title)}</h1>
        </div>
        <div class="flex gap-sm">
          <button class="btn btn-ghost btn-sm" id="editor-validate-btn">Validate</button>
          <button class="btn btn-primary btn-sm" id="editor-save-btn">Save</button>
        </div>
      </div>

      <div class="editor-layout">
        <div class="editor-pane">
          <div class="editor-pane-header">
            <span>YAML Editor</span>
            <span class="text-muted text-xs" id="editor-status">Ready</span>
          </div>
          <textarea class="editor-textarea" id="editor-yaml" spellcheck="false">${escapeHtml(originalContent)}</textarea>
        </div>
        <div class="editor-pane">
          <div class="editor-pane-header">
            <span>Preview</span>
            <span class="text-muted text-xs" id="editor-preview-status">—</span>
          </div>
          <div class="editor-preview" id="editor-preview"></div>
        </div>
      </div>

      <div id="editor-error" class="editor-error hidden"></div>
    `;

    const yamlEl = document.getElementById("editor-yaml");
    const previewEl = document.getElementById("editor-preview");
    const errorEl = document.getElementById("editor-error");

    // Live preview on input
    let debounceTimer = null;
    yamlEl.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => _updatePreview(yamlEl, previewEl, errorEl), 300);
    });

    // Tab key support in textarea
    yamlEl.addEventListener("keydown", (e) => {
      if (e.key === "Tab") {
        e.preventDefault();
        const start = yamlEl.selectionStart;
        const end = yamlEl.selectionEnd;
        yamlEl.value = yamlEl.value.substring(0, start) + "  " + yamlEl.value.substring(end);
        yamlEl.selectionStart = yamlEl.selectionEnd = start + 2;
      }
    });

    // Validate button
    document.getElementById("editor-validate-btn")?.addEventListener("click", async () => {
      const content = yamlEl.value;
      try {
        const result = await SentinelAPI.validateScenario(content);
        if (result.valid) {
          showToast("YAML is valid" + (result.errors?.length ? ` (${result.errors.join(", ")})` : ""), "success");
        } else {
          showToast("Invalid YAML: " + (result.errors?.join(", ") || "Unknown error"), "error");
        }
      } catch (err) {
        showToast("Validation failed: " + err.message, "error");
      }
    });

    // Save button
    document.getElementById("editor-save-btn")?.addEventListener("click", async () => {
      const content = yamlEl.value;
      document.getElementById("editor-status").textContent = "Saving…";
      try {
        const result = await SentinelAPI.saveScenario(id === "__new__" ? _extractId(content) : id, content);
        showToast(result.message || "Saved!", "success");
        document.getElementById("editor-status").textContent = "Saved";
        // Navigate to the scenario detail
        setTimeout(() => window.SentinelRouter.navigate(`#/scenarios/${result.id}`), 500);
      } catch (err) {
        showToast("Save failed: " + err.message, "error");
        document.getElementById("editor-status").textContent = "Error";
      }
    });

    // Initial preview
    _updatePreview(yamlEl, previewEl, errorEl);
  };

  function _updatePreview(yamlEl, previewEl, errorEl) {
    const content = yamlEl.value;
    try {
      // Simple YAML preview without a library — extract key fields with regex
      const idMatch = content.match(/^id:\s*(.+)$/m);
      const nameMatch = content.match(/^name:\s*(.+)$/m);
      const descMatch = content.match(/^description:\s*[|>]?\s*\n((?:\s+.+\n)*)/m);
      const taskMatch = content.match(/^task:\s*["']?(.+?)["']?\s*$/m);
      const tagsMatch = content.match(/^tags:\s*\n((?:\s+-\s+.+\n)*)/m);
      const timeoutMatch = content.match(/^timeout_seconds:\s*(\d+)/m);

      const id = idMatch ? idMatch[1].trim() : "—";
      const name = nameMatch ? nameMatch[1].trim() : "—";
      const task = taskMatch ? taskMatch[1].trim() : "—";
      const timeout = timeoutMatch ? timeoutMatch[1] + "s" : "30s";

      const tags = [];
      if (tagsMatch) {
        const tagLines = tagsMatch[1].split("\n");
        for (const line of tagLines) {
          const m = line.match(/^\s+-\s+(.+)$/);
          if (m) tags.push(m[1].trim());
        }
      }

      const desc = descMatch ? descMatch[1].trim().replace(/\n\s+/g, " ") : "";

      previewEl.innerHTML = `
        <div style="padding:0.5rem;">
          <div style="margin-bottom:0.75rem;">
            <span class="text-xs text-muted" style="text-transform:uppercase; letter-spacing:0.05em;">ID</span><br>
            <span class="text-sm" style="font-family:var(--font-mono);">${escapeHtml(id)}</span>
          </div>
          <div style="margin-bottom:0.75rem;">
            <span class="text-xs text-muted" style="text-transform:uppercase; letter-spacing:0.05em;">Name</span><br>
            <span class="text-sm">${escapeHtml(name)}</span>
          </div>
          ${desc ? `<div style="margin-bottom:0.75rem;">
            <span class="text-xs text-muted" style="text-transform:uppercase; letter-spacing:0.05em;">Description</span><br>
            <span class="text-sm text-muted">${escapeHtml(desc)}</span>
          </div>` : ''}
          <div style="margin-bottom:0.75rem;">
            <span class="text-xs text-muted" style="text-transform:uppercase; letter-spacing:0.05em;">Task</span><br>
            <span class="text-sm" style="font-family:var(--font-mono);">${escapeHtml(task)}</span>
          </div>
          <div style="margin-bottom:0.75rem;">
            <span class="text-xs text-muted" style="text-transform:uppercase; letter-spacing:0.05em;">Tags</span><br>
            ${tags.length ? tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join(' ') : '<span class="text-muted text-sm">None</span>'}
          </div>
          <div>
            <span class="text-xs text-muted" style="text-transform:uppercase; letter-spacing:0.05em;">Timeout</span><br>
            <span class="text-sm">${escapeHtml(timeout)}</span>
          </div>
        </div>
      `;

      errorEl.classList.add("hidden");
      document.getElementById("editor-preview-status").textContent = "Valid";
    } catch (err) {
      errorEl.textContent = "Parse error: " + err.message;
      errorEl.classList.remove("hidden");
      document.getElementById("editor-preview-status").textContent = "Error";
    }
  }

  function _extractId(yamlContent) {
    const m = yamlContent.match(/^id:\s*(.+)$/m);
    return m ? m[1].trim() : "unknown";
  }

  function _scenarioToYaml(s) {
    let yaml = `id: ${s.id || "unknown"}\n`;
    yaml += `name: ${s.name || ""}\n`;
    if (s.description) yaml += `description: |\n  ${s.description}\n`;
    if (s.task) yaml += `task: "${s.task}"\n`;
    if (s.tags && s.tags.length) {
      yaml += "tags:\n";
      for (const t of s.tags) yaml += `  - ${t}\n`;
    }
    yaml += `timeout_seconds: ${s.timeout_seconds || 30}\n`;
    return yaml;
  }

  function _blankScenarioYaml() {
    return `id: new-scenario-001
name: New Scenario
description: |
  Describe what this scenario tests.
task: "What should the agent do?"
env_config:
  tools:
    tool_name:
      response:
        result: "mock response"
tags:
  - basic
timeout_seconds: 30
`;
  }
})();
