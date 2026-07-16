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
    { pattern: /^#?\/scenarios\/(.+)$/, handler: renderScenarioDetail },
    { pattern: /^#?\/runs$/, handler: renderRuns },
    { pattern: /^#?\/runs\/(.+)$/, handler: renderRunDetail },
    { pattern: /^#?\/baselines$/, handler: renderBaselines },
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
      try {
        const result = matched.handler(container, ...matched.params);
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
})();
