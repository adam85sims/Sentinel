/**
 * Sentinel WebUI — Main Application Orchestrator
 *
 * Initializes the router, registers route handlers, and manages
 * navigation state. This is the entry point for the SPA.
 */
(function () {
  "use strict";

  // ── Route table ──
  // Maps route patterns to their renderer functions.
  // Each renderer receives (container, params) and populates the DOM.
  const routes = [
    { pattern: /^#?\/?$/, handler: renderDashboard },
    { pattern: /^#?\/scenarios$/, handler: renderScenarios },
    { pattern: /^#?\/scenarios\/__new__$/, handler: (id) => renderScenarioEditor('__new__') },
    { pattern: /^#?\/scenarios\/(.+)\/edit$/, handler: (id) => renderScenarioEditor(id) },
    { pattern: /^#?\/scenarios\/(.+)$/, handler: renderScenarioDetail },
    { pattern: /^#?\/runs$/, handler: renderRuns },
    { pattern: /^#?\/runs\/(.+)$/, handler: renderRunDetail },
    { pattern: /^#?\/baselines$/, handler: renderBaselines },
    { pattern: /^#?\/chaos$/, handler: renderChaosBuilder },
    { pattern: /^#?\/governance$/, handler: renderGovernance },
    { pattern: /^#?\/settings$/, handler: renderSettings },
  ];

  // ── Active state ──
  let currentRoute = null;
  let streamManager = null;

  /**
   * Match a hash against route patterns and return {handler, params}.
   */
  function matchRoute(hash) {
    const path = hash || "#/";
    for (const route of routes) {
      const match = path.match(route.pattern);
      if (match) {
        const params = match.slice(1); // captured groups
        return { handler: route.handler, params };
      }
    }
    return null;
  }

  /**
   * Navigate to a hash and render the corresponding page.
   */
  function navigate(hash) {
    if (!hash || hash === "") hash = "#/";

    // Avoid re-rendering the same route
    if (hash === currentRoute) return;
    currentRoute = hash;

    const container = document.getElementById("app-content");
    if (!container) return;

    // Disconnect any active SSE streams
    if (streamManager) {
      streamManager.disconnect();
      streamManager = null;
    }

    const matched = matchRoute(hash);
    if (matched) {
      // Show loading state
      container.innerHTML = '<div class="loading-spinner"></div>';

      // Call the page renderer (may be async)
      // Note: render functions use document.getElementById('app-content')
      // directly, so we don't pass container — only the route params.
      try {
        const result = matched.handler(...matched.params);
        // If it returns a promise, handle errors
        if (result && typeof result.catch === "function") {
          result.catch((err) => {
            container.innerHTML = renderError(
              "Failed to load page",
              err.message
            );
          });
        }
      } catch (err) {
        container.innerHTML = renderError("Page error", err.message);
      }
    } else {
      container.innerHTML = renderError("404", "Page not found");
    }

    // Update nav highlighting
    updateNav(hash);
  }

  /**
   * Highlight the active nav link based on current hash.
   */
  function updateNav(hash) {
    document.querySelectorAll(".nav-link").forEach((link) => {
      const href = link.getAttribute("href");
      if (!href) return;

      const isActive =
        (href === "#/" && (hash === "#/" || hash === "#")) ||
        (href !== "#/" && hash.startsWith(href));

      link.classList.toggle("active", isActive);
    });
  }

  /**
   * Render an error state.
   */
  function renderError(title, message) {
    return `
      <div class="empty-state">
        <div class="empty-state-icon">⚠</div>
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(message)}</p>
        <button class="btn btn-primary" onclick="location.hash='#/'">
          Go Home
        </button>
      </div>
    `;
  }

  /**
   * Escape HTML to prevent XSS in template literals.
   */
  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  /**
   * Format a timestamp for display.
   */
  function formatTime(ts) {
    if (!ts) return "—";
    const d = new Date(typeof ts === "number" ? ts * 1000 : ts);
    return d.toLocaleString();
  }

  /**
   * Format duration in milliseconds to human-readable.
   */
  function formatDuration(ms) {
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  }

  /**
   * Show a temporary toast notification.
   */
  function showToast(message, type = "info") {
    const container =
      document.getElementById("toast-container") || createToastContainer();
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.classList.add("show"), 10);
    setTimeout(() => {
      toast.classList.remove("show");
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  function createToastContainer() {
    const container = document.createElement("div");
    container.id = "toast-container";
    document.body.appendChild(container);
    return container;
  }

  // ── Initialize on DOM ready ──
  document.addEventListener("DOMContentLoaded", () => {
    // Handle hash changes
    window.addEventListener("hashchange", () => {
      navigate(location.hash);
    });

    // Initial route
    navigate(location.hash || "#/");

    // Log console toggle
    const toggle = document.getElementById("console-toggle");
    const console_ = document.getElementById("live-console");
    if (toggle && console_) {
      toggle.addEventListener("click", () => {
        console_.classList.toggle("collapsed");
        toggle.textContent = console_.classList.contains("collapsed")
          ? "▲ Logs"
          : "▼ Logs";
      });
    }

    // ── Light/Dark mode toggle ──
    const themeBtn = document.getElementById("theme-toggle");
    if (themeBtn) {
      const saved = localStorage.getItem("sentinel-theme");
      if (saved === "light") document.documentElement.setAttribute("data-theme", "light");

      themeBtn.addEventListener("click", () => {
        const isLight = document.documentElement.getAttribute("data-theme") === "light";
        if (isLight) {
          document.documentElement.removeAttribute("data-theme");
          localStorage.setItem("sentinel-theme", "dark");
        } else {
          document.documentElement.setAttribute("data-theme", "light");
          localStorage.setItem("sentinel-theme", "light");
        }
      });
    }

    // ── Keyboard shortcuts ──
    let pendingKey = null;
    let pendingTimeout = null;

    document.addEventListener("keydown", (e) => {
      // Don't trigger shortcuts when typing in inputs
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;

      // ? — show help
      if (e.key === "?" && !e.ctrlKey && !e.metaKey) {
        _showShortcutHelp();
        return;
      }

      // Escape — close help overlay
      if (e.key === "Escape") {
        const overlay = document.getElementById("shortcut-help-overlay");
        if (overlay) overlay.remove();
        return;
      }

      // Two-key combos: g + d/s/r/b/c/g
      if (pendingKey === "g") {
        clearTimeout(pendingTimeout);
        pendingKey = null;
        const routeMap = { d: "#/", s: "#/scenarios", r: "#/runs", b: "#/baselines", c: "#/chaos", g: "#/governance" };
        if (routeMap[e.key]) {
          e.preventDefault();
          navigate(routeMap[e.key]);
          window.location.hash = routeMap[e.key];
        }
        return;
      }

      if (e.key === "g" && !e.ctrlKey && !e.metaKey) {
        pendingKey = "g";
        pendingTimeout = setTimeout(() => { pendingKey = null; }, 800);
        return;
      }
    });
  });

  // ── Expose utilities for other modules ──
  window.SentinelApp = {
    navigate,
    escapeHtml,
    formatTime,
    formatDuration,
    showToast,
    getStreamManager: () => streamManager,
    setStreamManager: (sm) => {
      streamManager = sm;
    },
  };

  /** Show keyboard shortcut help overlay */
  function _showShortcutHelp() {
    if (document.getElementById("shortcut-help-overlay")) return;
    const overlay = document.createElement("div");
    overlay.id = "shortcut-help-overlay";
    overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center;";
    overlay.innerHTML = `
      <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius-lg);padding:1.5rem;max-width:400px;width:90%;box-shadow:var(--shadow-lg);">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
          <h3 style="margin:0;font-size:1rem;">Keyboard Shortcuts</h3>
          <button onclick="document.getElementById('shortcut-help-overlay').remove()" style="background:none;border:none;color:var(--fg-muted);cursor:pointer;font-size:1.2rem;">&times;</button>
        </div>
        <div style="font-size:0.85rem;line-height:1.8;">
          <div><kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">g</kbd> then <kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">d</kbd> — Dashboard</div>
          <div><kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">g</kbd> then <kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">s</kbd> — Scenarios</div>
          <div><kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">g</kbd> then <kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">r</kbd> — Runs</div>
          <div><kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">g</kbd> then <kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">b</kbd> — Baselines</div>
          <div><kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">g</kbd> then <kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">c</kbd> — Chaos</div>
          <div><kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">g</kbd> then <kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">g</kbd> — Governance</div>
          <div><kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">?</kbd> — Show this help</div>
          <div><kbd style="background:var(--bg-tertiary);padding:2px 6px;border-radius:3px;font-family:var(--font-mono);font-size:0.8rem;">Esc</kbd> — Close overlay</div>
        </div>
      </div>
    `;
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
  }
})();
