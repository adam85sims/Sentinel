/**
 * Sentinel Hash Router
 * Routes: #/ (dashboard), #/scenarios, #/scenarios/:id, #/runs, #/runs/:id, #/baselines, #/settings
 */
class Router {
  constructor() {
    this._routes = [];
    this._onChange = null;
    this._onPopState = this._onPopState.bind(this);
  }

  init() {
    window.addEventListener('hashchange', this._onPopState);
    // Trigger initial route
    this._onPopState();
  }

  register(pattern, callback) {
    this._routes.push({ pattern, callback });
  }

  onRouteChange(callback) {
    this._onChange = callback;
  }

  navigate(hash) {
    window.location.hash = hash;
  }

  _onPopState() {
    const hash = window.location.hash || '#/';
    const path = hash.slice(1); // strip '#'

    for (const route of this._routes) {
      const params = this._match(route.pattern, path);
      if (params !== null) {
        if (this._onChange) this._onChange(route.pattern, params);
        route.callback(params);
        return;
      }
    }
    // Default: go to dashboard
    this.navigate('#/');
  }

  _match(pattern, path) {
    const patternParts = pattern.split('/').filter(Boolean);
    const pathParts = path.split('/').filter(Boolean);

    if (patternParts.length !== pathParts.length) return null;

    const params = {};
    for (let i = 0; i < patternParts.length; i++) {
      if (patternParts[i].startsWith(':')) {
        params[patternParts[i].slice(1)] = decodeURIComponent(pathParts[i]);
      } else if (patternParts[i] !== pathParts[i]) {
        return null;
      }
    }
    return params;
  }
}

window.SentinelRouter = new Router();
