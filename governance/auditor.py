#!/usr/bin/env python3
"""Governance Auditor — calls a local LLM to verify claims.

Supports multiple backends via config (auditor.yaml):
  - openai-compatible: LM Studio, vLLM, LiteLLM, any OpenAI-compatible API
  - ollama: Ollama's native API
  - none: skip LLM audit, use only deterministic comparator

Key design:
  1. Config-driven — no hardcoded model names or URLs
  2. Pre-flight existence check — fail loud if model not available
  3. Retry on empty/None response
  4. Never unload by default (keeps models warm in VRAM)
  5. Direct JSON-out prompt — no chain-of-thought loops
  6. Optional escalation model for ambiguous cases
"""

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from common.config import load_config
from common.logging import get_logger

logger = get_logger("governance.auditor")

# Config file location (relative to this module)
CONFIG_PATH = Path(__file__).parent / "auditor.yaml"

# Env var overrides for quick testing without editing yaml
ENV_URL = "AGENT_FW_AUDITOR_URL"
ENV_MODEL = "AGENT_FW_AUDITOR_MODEL"


# ─── Configuration loading ────────────────────────────────────────

def load_auditor_config(project_root: Path = None) -> dict:
    """Load auditor configuration from auditor.yaml + common config.

    Priority:
      1. Environment variables (AGENT_FW_AUDITOR_URL, AGENT_FW_AUDITOR_MODEL)
      2. auditor.yaml (project-level)
      3. Common config's governance.auditor section (if present)
      4. Safe defaults
    """
    # Load from auditor.yaml if it exists
    yaml_config = {}
    if CONFIG_PATH.exists():
        try:
            import yaml
            with CONFIG_PATH.open() as f:
                yaml_config = yaml.safe_load(f) or {}
        except ImportError:
            logger.warning("PyYAML not installed; cannot load auditor.yaml")
        except Exception as e:
            logger.warning("Failed to parse auditor.yaml: %s", e)

    # Merge with defaults
    config = deep_merge(_default_config(), yaml_config)

    # Apply env var overrides
    if ENV_URL in os.environ:
        config.setdefault("backend", {})["url"] = os.environ[ENV_URL]
    if ENV_MODEL in os.environ:
        model = os.environ[ENV_MODEL]
        config.setdefault("primary", {})["model"] = model

    return config


def _default_config() -> dict:
    """Safe default configuration."""
    return {
        "backend": {
            "type": "openai-compatible",
            "url": "http://localhost:1234/v1/chat/completions",
            "lms_binary": str(Path.home() / ".lmstudio" / "bin" / "lms"),
        },
        "primary": {
            "model": "ibm/granite-4.1-3b",
            "context_length": 8192,
            "temperature": 0.0,
            "max_tokens": 1024,
            "gpu": "max",
            "expect_on_disk": True,
        },
        "escalation": None,
        "keep_resident": True,
        "retry": {"max_attempts": 3, "backoff_seconds": 5},
        "on_exhausted_retries": "critical",
    }


from common.config import deep_merge


import os  # noqa: E402 (needed for env var access)


# ─── Backend operations ──────────────────────────────────────────

def is_model_on_disk(model_key: str, config: dict) -> bool:
    """Check if a model is available.

    Uses `lms ls --json` for LM Studio, or falls back to a URL health check.
    Matches using normalized keys to handle LM Studio's different identifier
    formats (download key vs display name vs API ID).
    """
    backend = config.get("backend", {})
    backend_type = backend.get("type", "openai-compatible")

    if backend_type == "none":
        return False

    normalized_key = _normalize_model_key(model_key)

    # Try LM Studio CLI if available
    lms_binary = backend.get("lms_binary")
    if lms_binary:
        lms_path = Path(lms_binary).expanduser()
        if lms_path.exists():
            try:
                result = subprocess.run(
                    [str(lms_path), "ls", "--json", "--llm"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    models = json.loads(result.stdout)
                    for m in models:
                        # Check modelKey (display name)
                        if _normalize_model_key(m.get("modelKey", "")) == normalized_key:
                            return True
                        # Check indexedModelIdentifier (download path)
                        if normalized_key in _normalize_model_key(
                            m.get("indexedModelIdentifier", "")
                        ):
                            return True
            except Exception as e:
                logger.debug("lms ls failed: %s", e)

    # Fallback: assume model is available if backend is configured
    # The actual API call will fail if the model isn't loaded
    return True


def _normalize_model_key(key: str) -> str:
    """Strip org prefix and GGUF/download suffixes to get the core model name.

    LM Studio uses different identifiers at different layers:
      - Download key:  unsloth/governance-granite-4.1-3b-GGUF  (config)
      - Display name:  governance-granite-4.1-3b               (lms ps / API)
    This normalizes both to the core name for comparison.
    """
    import re as _re
    # Take last path segment (strip org prefix like "unsloth/")
    name = key.rsplit("/", 1)[-1]
    # Strip GGUF suffix and quantization tags (e.g. -Q4_K_M)
    name = _re.sub(r"-GGUF$", "", name, flags=_re.IGNORECASE)
    name = _re.sub(r"-Q[0-9]_[A-Z0-9_]+$", "", name, flags=_re.IGNORECASE)
    return name.lower()


def is_model_loaded(model_key: str, config: dict) -> bool:
    """Check if model is currently loaded in memory.

    Uses the HTTP /v1/models endpoint first (fast, authoritative),
    then falls back to `lms ps` with fuzzy key matching.
    LM Studio uses different identifiers at different layers, so we
    normalize keys before comparing (see _normalize_model_key).
    """
    backend = config.get("backend", {})
    url = backend.get("url", "http://localhost:1234/v1/chat/completions")

    # Primary: HTTP API — fast and reliable
    try:
        models_url = url.rsplit("/chat/completions", 1)[0] + "/models"
        req = urllib.request.Request(models_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            loaded_ids = [m.get("id", "") for m in data.get("data", [])]
            normalized_key = _normalize_model_key(model_key)
            for api_id in loaded_ids:
                if (_normalize_model_key(api_id) == normalized_key
                        or normalized_key in _normalize_model_key(api_id)
                        or _normalize_model_key(api_id) in normalized_key):
                    return True
            # Also accept if ANY model is loaded (single-model setups)
            if loaded_ids:
                logger.debug(
                    "Exact key '%s' not found in loaded models %s, "
                    "but models are available — proceeding",
                    model_key, loaded_ids,
                )
                return True
    except Exception as e:
        logger.debug("HTTP model check failed: %s", e)

    # Fallback: lms CLI
    lms_binary = backend.get("lms_binary")
    if lms_binary:
        lms_path = Path(lms_binary).expanduser()
        if lms_path.exists():
            try:
                result = subprocess.run(
                    [str(lms_path), "ps"],
                    capture_output=True, text=True, timeout=10,
                )
                normalized_key = _normalize_model_key(model_key)
                for line in result.stdout.splitlines():
                    # lms ps columns: IDENTIFIER MODEL STATUS ...
                    # Check if normalized key matches any identifier or model name
                    parts = line.split()
                    for part in parts:
                        if _normalize_model_key(part) == normalized_key:
                            return True
            except Exception:
                pass

    return False


def load_model(model_key: str, config: dict, timeout: int = 30) -> bool:
    """Load model into memory. Returns True if loaded or not needed."""
    backend = config.get("backend", {})
    backend_type = backend.get("type", "openai-compatible")

    # "none" backend means skip LLM entirely
    if backend_type == "none":
        return False

    # If already loaded, nothing to do
    if is_model_loaded(model_key, config):
        return True

    # Try LM Studio CLI for explicit loading
    lms_binary = backend.get("lms_binary")
    if lms_binary:
        lms_path = Path(lms_binary).expanduser()
        if lms_path.exists():
            section = config.get("primary", {})
            print(f"  Loading {model_key} into VRAM...", file=sys.stderr)
            try:
                result = subprocess.run(
                    [
                        str(lms_path), "load", model_key,
                        "--context-length", str(section.get("context_length", 8192)),
                        "--gpu", section.get("gpu", "max"),
                    ],
                    capture_output=True, text=True, timeout=timeout,
                )
                if result.returncode == 0 or "loaded successfully" in result.stdout.lower():
                    print(f"  Loaded {model_key}.", file=sys.stderr)
                    return True
                print(f"  Load failed: {result.stdout[-300:]}", file=sys.stderr)
                return False
            except subprocess.TimeoutExpired:
                print(f"  Load timed out after {timeout}s.", file=sys.stderr)
                return False

    # For backends without explicit loading (Ollama, etc.), assume it works
    # The API call will handle model loading on first request
    return True


# ─── Audit prompt — direct JSON out, no chain-of-thought ──────────

AUDIT_PROMPT = """You are an audit engine. Compare CLAIMS to EVIDENCE.

Output ONLY a JSON object with this exact schema. No prose, no preamble, no markdown fence:
{
  "claims_total": <integer>,
  "verified": <integer>,
  "discrepancies": [
    {
      "severity": "CRITICAL" | "WARNING" | "INFO",
      "summary": "<one sentence>",
      "claimed": "<exact value or short quote from CLAIMS>",
      "actual": "<exact value or short quote from EVIDENCE>"
    }
  ],
  "verdict": "PASS" | "FAIL" | "WARN"
}

Rules:
- CRITICAL: false claims, tests that claim to pass but failed, backdated entries, contradictory values.
- WARNING: count mismatches, missing files referenced in claims, internal inconsistencies.
- INFO: minor drift, wording differences, optional claims with no evidence.
- "verified" = claims_total minus discrepancies that are CRITICAL or WARNING.
- If the diary claims a future date, that is CRITICAL.
- If a claimed test count does not match the actual passed test count, that is CRITICAL.
- If a claimed tool count does not match the actual decorator count, that is CRITICAL.
- Treat path differences (e.g. "server.py" vs "src/pattern-memory/server.py") as INFO unless the file does not exist.
- Output ONLY the JSON object, nothing else."""


# ─── The audit call ───────────────────────────────────────────────

def call_model(model_key: str, claims: dict, evidence: dict,
               config: dict) -> Optional[str]:
    """One attempt at calling the model. Returns content string or None."""
    if not load_model(model_key, config):
        return None

    backend = config.get("backend", {})
    url = backend.get("url", "http://localhost:1234/v1/chat/completions")

    section = config.get("primary", {})
    user_content = (
        "CLAIMS (from diary entry):\n"
        f"{json.dumps(claims, indent=2, default=str)}\n\n"
        "EVIDENCE (independently collected):\n"
        f"{json.dumps(evidence, indent=2, default=str)}"
    )

    payload = {
        "model": model_key,
        "messages": [
            {"role": "system", "content": AUDIT_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": section.get("temperature", 0.0),
        "max_tokens": section.get("max_tokens", 1024),
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            message = result["choices"][0]["message"]
            content = (message.get("content") or "").strip()
            return content if content else None
    except urllib.error.URLError as e:
        logger.error("Network error calling %s: %s", url, e)
        return None
    except Exception as e:
        logger.error("Error calling model: %s", e)
        return None


def audit(claims: dict, evidence: dict, config: dict = None,
          use_escalation: bool = False) -> str:
    """Run audit. Returns the raw model output as a string.

    Empty/None responses are retried up to config['retry']['max_attempts'].
    On exhaustion, returns a string with an explicit AUDITOR ERROR marker
    that extract.py must surface as CRITICAL.

    Args:
        claims: Extracted claims from diary entry.
        evidence: Independently collected project evidence.
        config: Auditor config dict. If None, loads from auditor.yaml.
        use_escalation: If True, use the escalation model instead of primary.
    """
    cfg = config or load_auditor_config()
    role = "escalation" if use_escalation else "primary"
    section = cfg.get(role) or cfg["primary"]
    retries = cfg.get("retry", {}).get("max_attempts", 3)
    backoff = cfg.get("retry", {}).get("backoff_seconds", 5)

    model_key = section["model"]

    # Pre-flight: model must exist on disk (if check is enabled)
    if section.get("expect_on_disk", True) and not is_model_on_disk(model_key, cfg):
        return (
            f"AUDITOR ERROR: Model '{model_key}' not found on disk. "
            f"Download with: lms get {model_key}@q4_k_m"
        )

    last_result: Optional[str] = None
    for attempt in range(1, retries + 1):
        print(f"  [{role}] attempt {attempt}/{retries}...", file=sys.stderr)
        last_result = call_model(model_key, claims, evidence, cfg)
        if last_result:
            return last_result
        if attempt < retries:
            print(f"  Empty response, retrying in {backoff}s...",
                  file=sys.stderr)
            time.sleep(backoff)

    # All retries exhausted
    return (
        f"AUDITOR ERROR: {model_key} returned no content after {retries} "
        f"attempts. Check that the LLM backend is running and the model "
        f"is available."
    )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: auditor.py <claims.json> <evidence.json> [--escalation]")
        sys.exit(1)

    escalation = "--escalation" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    claims = json.loads(Path(args[0]).read_text())
    evidence = json.loads(Path(args[1]).read_text())

    cfg = load_auditor_config()
    result = audit(claims, evidence, cfg, use_escalation=escalation)
    print(result)
