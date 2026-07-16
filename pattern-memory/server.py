"""Pattern Memory — MCP Server (Consolidated)

An MCP server that learns behavioral patterns from user corrections
and injects them into agent context.

Consolidated from 24 tools → 13 tools for cleaner agent ergonomics.
"""
import json
import os
import signal
import sys
from pathlib import Path

# Add own dir + grandparent to path for imports
# (storage.py imports from common/ which lives in the parent project)
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from config import get_config
from models import Pattern, Correction
from storage import Storage
from pattern_engine import (
    PatternEngine,
    correction_score,
    correction_score_v2,
    correction_score_llm,
    correction_score_hybrid,
    is_correction,
    classify_correction as _classify_correction,
    find_conflicts,
    detect_opposition,
    find_context_scoped_conflicts,
    find_all_conflicts_classified,
)

# ── Initialize ──────────────────────────────────────────────────────────

_config = get_config()
PID_FILE = Path(_config["pid_file"])

mcp = FastMCP("pattern-memory")
storage = Storage(
    db_path=_config["db_path"],
    chroma_url=_config["chroma_url"],
    collection_name=_config["collection_name"],
)
engine = PatternEngine(storage)


# ── MCP Tools (Consolidated: 13 tools) ─────────────────────────────────
#
# Tool taxonomy:
#   INPUT:    record_correction, classify_correction
#   RETRIEVE: get_patterns, search_patterns, list_patterns, get_session_context
#   RATE:     rate_pattern
#   MAINTAIN: get_stats, run_decay
#   PRE-CHECK: check_before_acting, check_conflicts, resolve_conflict
#   TRACK:    mark_pattern_applied

# ── INPUT ───────────────────────────────────────────────────────────────

@mcp.tool()
def record_correction(
    original: str,
    corrected: str,
    context: str = "",
    category: str = "",
) -> str:
    """Record when a user corrects agent behavior.

    Use this when the agent did something wrong and the user provides
    the correct behavior. The engine will extract and store a pattern.

    Args:
        original: What the agent did wrong (e.g., "used 85% threshold")
        corrected: What the user wanted instead (e.g., "use 80% threshold")
        context: What was being worked on (e.g., "image processing pipeline")
        category: Optional hint: code_style, threshold, tool_choice, workflow, exclusion
    """
    result = engine.record_correction(
        original=original,
        corrected=corrected,
        context=context,
        category=category or None,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def classify_correction(
    text: str = "",
    texts: list[str] = [],
    method: str = "regex",
    model: str = "gpt-4o-mini",
) -> str:
    """Classify user messages as corrections using regex or hybrid detection.

    Supports single text or batch mode. For batch, pass texts=[].

    Args:
        text: Single user message to classify
        texts: List of user messages for batch classification
        method: "regex" (fast, free) or "hybrid" (regex + LLM, more accurate)
        model: LLM model for hybrid mode (default: gpt-4o-mini)

    Returns:
        JSON with is_correction, confidence, category, and method.
        For batch: JSON array with results for each message.
    """
    # Batch mode
    if texts:
        results = []
        for t in texts:
            score = correction_score_v2(t)
            category = _classify_correction(t)
            results.append({
                "text": t[:100] + "..." if len(t) > 100 else t,
                "is_correction": score >= 0.3,
                "confidence": score,
                "category": category,
            })
        return json.dumps(results, indent=2)

    # Single text mode
    if method == "hybrid":
        result = correction_score_hybrid(
            text,
            llm_client=None,  # No LLM client in standalone mode
            regex_threshold=0.6,
            llm_threshold=0.5,
        )
        return json.dumps(result, indent=2)
    else:
        score = correction_score_v2(text)
        category = _classify_correction(text)
        result = {
            "is_correction": score >= 0.3,
            "confidence": score,
            "category": category,
            "method": "regex",
        }
        return json.dumps(result, indent=2)


# ── RETRIEVE ────────────────────────────────────────────────────────────

@mcp.tool()
def get_patterns(
    context: str,
    limit: int = 5,
    min_confidence: float = 0.3,
) -> str:
    """Get patterns relevant to the current context.

    Call this at the start of a session or before acting to retrieve
    learned patterns that apply to the current task.

    Args:
        context: Description of the current task or context
        limit: Maximum patterns to return (default: 5)
        min_confidence: Minimum confidence threshold (default: 0.3)
    """
    results = engine.get_patterns_for_context(
        context=context,
        limit=limit,
        min_confidence=min_confidence,
    )
    return json.dumps(results, indent=2, default=str)


@mcp.tool()
def search_patterns(
    query: str,
    limit: int = 10,
) -> str:
    """Search patterns by semantic similarity.

    Args:
        query: What to search for (e.g., "code formatting preferences")
        limit: Maximum results (default: 10)
    """
    results = storage.search_patterns(query, limit=limit)
    return json.dumps(results, indent=2, default=str)


@mcp.tool()
def list_patterns(
    category: str = "",
    sort: str = "confidence",
    limit: int = 20,
) -> str:
    """List all learned patterns.

    Args:
        category: Filter by category (optional)
        sort: Sort by 'confidence', 'recent', or 'usage' (default: 'confidence')
        limit: Maximum patterns to return (default: 20)
    """
    patterns = storage.list_patterns(
        category=category or None,
        sort_by=sort,
        limit=limit,
    )
    return json.dumps([p.to_dict() for p in patterns], indent=2, default=str)


@mcp.tool()
def get_session_context(
    limit: int = 20,
    min_confidence: float = 0.5,
) -> str:
    """Get high-confidence behavioral patterns for this session.

    Call at the start of every session to load learned preferences.
    Returns patterns that should guide the agent's behavior throughout
    the session.

    Args:
        limit: Maximum patterns to return (default: 20)
        min_confidence: Minimum confidence threshold (default: 0.5)

    Returns:
        Formatted list of behavioral rules, or "No patterns learned yet."
    """
    patterns = storage.list_patterns(
        min_confidence=min_confidence,
        sort_by="confidence",
        limit=limit,
    )

    if not patterns:
        return "No patterns learned yet. Proceed with default behavior."

    rules = []
    for p in patterns:
        confidence = p.confidence
        action = p.action
        rules.append(f"• [{confidence:.0%}] {action}")

    header = f"Learned Behavioral Rules ({len(rules)} patterns):"
    return header + "\n" + "\n".join(rules)


# ── RATE ────────────────────────────────────────────────────────────────

@mcp.tool()
def rate_pattern(
    pattern_id: str,
    action: str = "confirm",
) -> str:
    """Rate a pattern as correct or incorrect.

    Confirming boosts confidence toward 1.0.
    Rejecting reduces confidence; very low patterns are removed.

    Args:
        pattern_id: The pattern ID to rate
        action: "confirm" to approve, "reject" to disapprove
    """
    if action == "reject":
        result = engine.reject_pattern(pattern_id)
    else:
        result = engine.confirm_pattern(pattern_id)
    return json.dumps(result, indent=2)


# ── MAINTAIN ────────────────────────────────────────────────────────────

@mcp.tool()
def get_stats() -> str:
    """Get pattern memory statistics and auto-confirm candidates.

    Returns total patterns, corrections, confidence distribution,
    and patterns eligible for auto-confirmation.
    """
    stats = engine.get_stats()
    # Add auto-confirmable info
    candidates = engine.get_auto_confirmable_patterns(min_applications=3)
    stats["auto_confirmable"] = len(candidates)
    stats["auto_confirmable_patterns"] = candidates
    return json.dumps(stats, indent=2)


@mcp.tool()
def run_decay(
    stale_days: int = 90,
    removal_threshold: float = 0.1,
    dry_run: bool = False,
) -> str:
    """Run confidence decay on stale patterns.

    Patterns not used in `stale_days` get their confidence recalculated.
    Patterns that decay below `removal_threshold` are deleted.
    Use dry_run=True to preview without making changes.

    Args:
        stale_days: Days of non-use before decay (default: 90)
        removal_threshold: Confidence below which patterns are removed (default: 0.1)
        dry_run: If True, preview changes without applying them (default: False)

    Returns:
        Decay statistics: patterns scanned, decayed, removed, kept.
    """
    result = engine.decay_stale_patterns(
        stale_days=stale_days,
        removal_threshold=removal_threshold,
        dry_run=dry_run,
    )
    return json.dumps(result, indent=2)


# ── PRE-CHECK ───────────────────────────────────────────────────────────

@mcp.tool()
def check_before_acting(
    action_type: str,
    context: str,
    limit: int = 3,
) -> str:
    """Check for learned patterns before taking an action.

    Call this BEFORE writing code, choosing tools, setting values, or
    making decisions. Returns relevant patterns that might apply to
    the intended action.

    Args:
        action_type: What you're about to do (e.g., "write JavaScript",
                     "choose threshold", "set variable", "write email")
        context: Additional context about the action (e.g., "React component",
                 "image processing", "formal tone")
        limit: Maximum patterns to return (default: 3)

    Returns:
        Formatted rules with confidence scores, or "No relevant patterns found."
    """
    query = f"{action_type} {context}"
    patterns = engine.get_patterns_for_context(
        context=query,
        limit=limit,
        min_confidence=0.3,
    )

    if not patterns:
        return "No relevant patterns found. Proceed with default behavior."

    rules = []
    for p in patterns:
        pattern_data = p["pattern"]
        confidence = pattern_data["confidence"]
        action = pattern_data["action"]
        rules.append(f"PATTERN ({confidence:.0%} confidence): {action}")

    return "\n".join(rules)


@mcp.tool()
def check_conflicts(
    type: str = "all",
) -> str:
    """Find conflicts between stored patterns.

    Args:
        type: "true" for same-context opposing actions (needs resolution),
              "context_scoped" for different-context opposing actions (informational),
              "all" for both (default)

    Returns:
        List of conflicts with severity, type, and pattern details.
    """
    if type == "true":
        conflicts = engine.get_all_conflicts()
    elif type == "context_scoped":
        conflicts = engine.get_all_context_scoped_conflicts()
    else:
        conflicts = engine.get_all_conflicts_classified()
    return json.dumps(conflicts, indent=2)


@mcp.tool()
def resolve_conflict(
    pattern_a_id: str,
    pattern_b_id: str,
    strategy: str = "confidence",
    loser_id: str = "",
) -> str:
    """Resolve a conflict between two patterns.

    Use this AFTER calling check_conflicts to act on a true_conflict.
    The winner is kept at its current confidence; the loser is
    penalized by -0.2 confidence (and removed if it drops below
    the 0.1 floor).

    Args:
        pattern_a_id: First pattern ID (the pair to resolve)
        pattern_b_id: Second pattern ID
        strategy: "confidence" (higher confidence wins, default),
                  "recency" (newer pattern wins),
                  "suppress" (manually pick the loser)
        loser_id: For "suppress" strategy, which pattern to penalize
                  (must match pattern_a_id or pattern_b_id)

    Returns:
        Resolution result: {action, winner_id, loser_id, winner_confidence,
        loser_confidence, removed}.
    """
    result = engine.resolve_conflict(
        pattern_a_id=pattern_a_id,
        pattern_b_id=pattern_b_id,
        strategy=strategy,
        loser_id=loser_id or None,
    )
    return json.dumps(result, indent=2)


# ── TRACK ───────────────────────────────────────────────────────────────

@mcp.tool()
def mark_pattern_applied(
    pattern_id: str,
) -> str:
    """Mark a pattern as applied (used via check_before_acting or get_session_context).

    Call this after retrieving a pattern and using it in your response.
    Tracks application count for auto-confirmation.

    Args:
        pattern_id: The pattern ID that was applied
    """
    result = engine.mark_pattern_applied(pattern_id)
    return json.dumps(result, indent=2)


# ── Entry Point ─────────────────────────────────────────────────────────

def _get_pid_file() -> Path:
    """Get the PID file path, ensuring the parent directory exists."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    return PID_FILE


def _check_singleton() -> None:
    """Check for a running instance and exit if found.

    Uses a PID file. If the PID file exists and the process is alive,
    exits with an error. If stale, removes it and proceeds.
    """
    pid_file = _get_pid_file()

    if pid_file.exists():
        try:
            existing_pid = int(pid_file.read_text().strip())
            # Check if process is still alive
            os.kill(existing_pid, 0)  # Signal 0 = test existence
            print(
                f"ERROR: Another pattern-memory-server is already running (PID {existing_pid}).",
                file=sys.stderr,
            )
            print(
                f"  PID file: {pid_file}",
                file=sys.stderr,
            )
            print(
                "  If the process is dead, remove the PID file and try again.",
                file=sys.stderr,
            )
            sys.exit(1)
        except (ValueError, OSError):
            # Stale PID — process no longer exists
            pid_file.unlink(missing_ok=True)

    # Write our PID
    pid_file.write_text(str(os.getpid()))


def _cleanup_pid_file(signum=None, frame=None):
    """Remove the PID file on shutdown."""
    try:
        pid_file = _get_pid_file()
        if pid_file.exists():
            pid_file.unlink()
    except Exception:
        pass
    if signum is not None:
        sys.exit(0)


def main():
    """Entry point for pattern-memory-server console script."""
    _check_singleton()

    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGTERM, _cleanup_pid_file)
    signal.signal(signal.SIGINT, _cleanup_pid_file)

    try:
        mcp.run()
    finally:
        _cleanup_pid_file()


if __name__ == "__main__":
    main()
