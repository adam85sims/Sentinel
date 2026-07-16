"""Pattern Memory — Pattern Engine

Core logic for correction detection, pattern extraction, and confidence scoring.
"""
import math
import re
from datetime import datetime, timedelta, UTC
from typing import Optional

from models import Pattern, Correction
from storage import Storage

# ── Correction Detection ────────────────────────────────────────────────

# ── Confidence Ceilings ─────────────────────────────────────────────────
# Auto-confirmed patterns (silence = approval) should NEVER reach full
# confidence. Only explicit human confirmation should hit 1.0.
AUTO_CONFIRM_CEILING = 0.7
EXPLICIT_CONFIRM_CEILING = 1.0

CORRECTION_SIGNALS = [
    r"\bno\b",
    r"\bactually\b",
    r"\binstead\b",
    r"\bi meant\b",
    r"\buse .+ not\b",
    r"\bprefer\b",
    r"\bnever .+ always\b",
    r"\bstop doing\b",
    r"\bdon't .+ do\b",
    r"\bshould be\b",
    r"\bthat's wrong\b",
    r"\bfix .+ to\b",
    r"\bchange .+ to\b",
    r"\brememb(er|ing)\b",
    r"\bfrom now on\b",
    r"\balways use\b",
    r"\bdon't use\b",
    # Additional patterns for better coverage
    r"\bplease use\b",
    r"\byou should\b",
    r"\bit should be\b",
    r"\bmake sure\b",
    r"\bdon't forget\b",
    r"\bremember to\b",
    r"\bnever forget\b",
    r"\buse this instead\b",
    r"\breplace with\b",
    r"\bswap\b",
    r"\bbetter\b",
    r"\bwrong\b",
    r"\bincorrect\b",
    r"\bnot .+ but\b",
    r"\brather than\b",
    r"\binstead of\b",
    r"\buse .+ instead\b",
    r"\bnever use\b",
    r"\bavoid\b",
    r"\bskip\b",
    r"\bremove\b",
    r"\bexclude\b",
]

CATEGORY_KEYWORDS = {
    "code_style": [
        "format", "indent", "style", "naming", "convention", "lint",
        "prettier", "eslint", "black", "isort", "autopep8", "flake8",
        "pylint", "mypy", "type hint", "docstring", "comment",
    ],
    "threshold": [
        "percent", "%", "threshold", "limit", "max", "min", "value",
        "number", "range", "between", "above", "below", "over", "under",
    ],
    "tool_choice": [
        "use .+ instead", "prefer .+ over", "switch to", "tool",
        "editor", "ide", "vscode", "vim", "emacs", "intellij", "pycharm",
        "sublime", "atom", "notepad++", "browser", "chrome", "firefox",
        "safari", "edge", "terminal", "shell", "bash", "zsh", "fish",
    ],
    "workflow": [
        "step", "first", "then", "before", "after", "process", "flow",
        "pipeline", "procedure", "sequence", "order", "stage", "phase",
    ],
    "exclusion": [
        "never", "don't", "avoid", "skip", "remove", "exclude",
        "stop", "halt", "terminate", "cancel", "abort", "quit",
    ],
    "tone": [
        "formal", "informal", "casual", "professional", "friendly",
        "polite", "rude", "harsh", "soft", "gentle", "strict",
    ],
    "language": [
        "english", "spanish", "french", "german", "chinese", "japanese",
        "korean", "portuguese", "russian", "arabic", "hindi",
    ],
}


# ── Opposition & Conflict Detection ────────────────────────────────────

# Known pairs of opposing concepts that indicate conflicting patterns
OPPOSITION_PAIRS = [
    # Code style — variable declarations
    ("const", "let"), ("const", "var"), ("let", "var"),
    # Whitespace
    ("tabs", "spaces"), ("spaces", "tabs"),
    # Quotes
    ("single quotes", "double quotes"), ("double quotes", "single quotes"),
    # Naming conventions
    ("camelcase", "snake_case"), ("snake_case", "camelcase"),
    ("pascalcase", "camelcase"), ("camelcase", "pascalcase"),
    # Formatters
    ("prettier", "eslint format"), ("black", "autopep8"),
    # Editors / tools
    ("vim", "emacs"), ("emacs", "vim"),
    ("vscode", "vim"), ("vscode", "intellij"),
    # Languages / frameworks
    ("react", "vue"), ("vue", "react"),
    ("typescript", "javascript"), ("javascript", "typescript"),
    # Async patterns
    ("async/await", ".then()"), (".then()", "async/await"),
    ("promises", "callbacks"), ("callbacks", "promises"),
    # Module systems
    ("es modules", "commonjs"), ("commonjs", "es modules"),
    ("import", "require"), ("require", "import"),
]

# ── Context Qualifiers ────────────────────────────────────────────────
# Context qualifiers help determine if two patterns apply to different
# domains (e.g., "React" vs "Node") even when they share trigger terms.

CONTEXT_QUALIFIERS = {
    # Languages
    "python", "javascript", "typescript", "java", "c", "c++", "c#",
    "go", "rust", "ruby", "php", "swift", "kotlin", "scala", "haskell",
    "elixir", "clojure", "r", "matlab", "perl", "lua", "dart",
    # Frameworks
    "react", "vue", "angular", "svelte", "next.js", "nuxt", "gatsby",
    "express", "fastapi", "django", "flask", "rails", "spring", "laravel",
    "flutter", "react native", "electron", "node.js",
    # File types / extensions
    ".tsx", ".jsx", ".ts", ".py", ".java", ".go", ".rs",
    ".rb", ".php", ".swift", ".kt", ".vue", ".svelte",
    # Project areas
    "frontend", "backend", "api", "database", "db", "config",
    "test", "tests", "testing", "spec", "docs", "documentation",
    "build", "ci", "cd", "deploy", "deployment",
    # Environments
    "development", "dev", "staging", "production", "prod", "test",
    # Code roles
    "component", "hook", "service", "util", "helper", "middleware",
    "controller", "model", "view", "route", "schema",
}


def extract_context_qualifiers(text: str) -> set[str]:
    """Extract context qualifiers from text.

    Looks for known context qualifiers (languages, frameworks, file types,
    project areas, environments) in the text.

    Args:
        text: The trigger or action text to analyze

    Returns:
        Set of found context qualifiers (lowercase)
    """
    text_lower = _normalize(text)
    found = set()
    for qualifier in CONTEXT_QUALIFIERS:
        # Use word boundary matching for short qualifiers
        if len(qualifier) <= 3:
            pattern = r"\b" + re.escape(qualifier) + r"\b"
            if re.search(pattern, text_lower):
                found.add(qualifier)
        else:
            if qualifier in text_lower:
                found.add(qualifier)
    return found


def contexts_overlap(context_a: set[str], context_b: set[str]) -> bool:
    """Check if two sets of context qualifiers overlap.

    Two contexts overlap if they share any qualifier, or if one is
    a subset of the other (e.g., "frontend" and "react" overlap
    because react is a frontend framework).

    Args:
        context_a: First set of context qualifiers
        context_b: Second set of context qualifiers

    Returns:
        True if contexts overlap (patterns may conflict)
    """
    # Direct overlap
    if context_a & context_b:
        return True

    # Check for semantic relationships (framework implies language)
    FRAMEWORK_LANGUAGE = {
        "react": {"javascript", "typescript", ".tsx", ".jsx", ".ts"},
        "vue": {"javascript", "typescript", ".vue", ".ts"},
        "angular": {"javascript", "typescript", ".ts"},
        "svelte": {"javascript", "typescript", ".svelte", ".ts"},
        "express": {"javascript", "typescript", ".ts"},
        "fastapi": {"python", ".py"},
        "django": {"python", ".py"},
        "flask": {"python", ".py"},
        "rails": {"ruby", ".rb"},
        "spring": {"java", ".java"},
        "laravel": {"php", ".php"},
        "flutter": {"dart"},
        "react native": {"javascript", "typescript", ".tsx", ".jsx", ".ts"},
        "next.js": {"javascript", "typescript", ".tsx", ".jsx", ".ts"},
        "nuxt": {"javascript", "typescript", ".vue", ".ts"},
    }

    # Check if a framework in one context implies a language in the other
    # But exclude node.js — it's a separate runtime, not just JavaScript
    for fw, langs in FRAMEWORK_LANGUAGE.items():
        if fw in context_a and langs & context_b:
            # Don't match if the other context is specifically node.js
            if "node.js" not in context_b:
                return True
        if fw in context_b and langs & context_a:
            # Don't match if the other context is specifically node.js
            if "node.js" not in context_a:
                return True

    return False


def is_context_scoped(
    pattern_a: Pattern, pattern_b: Pattern,
    context_a: set[str], context_b: set[str],
) -> bool:
    """Determine if a conflict between two patterns is context-scoped.

    A conflict is context-scoped if the patterns have opposing actions
    but apply to different contexts (e.g., "use const in React" vs
    "use let in Node").

    Args:
        pattern_a: First pattern
        pattern_b: Second pattern
        context_a: Context qualifiers from pattern A
        context_b: Context qualifiers from pattern B

    Returns:
        True if the conflict is context-scoped (not a true conflict)
    """
    # If either pattern has no context qualifiers, we can't determine scope
    if not context_a or not context_b:
        return False

    # If contexts don't overlap, the conflict is context-scoped
    return not contexts_overlap(context_a, context_b)


def find_context_scoped_conflicts(pattern_a: Pattern, pattern_b: Pattern) -> dict | None:
    """Find conflicts that are context-scoped (different contexts).

    Unlike find_conflicts which identifies true conflicts (same context,
    opposing actions), this identifies patterns that would conflict if
    they applied to the same context, but don't because they target
    different domains.

    Args:
        pattern_a: First pattern
        pattern_b: Second pattern

    Returns:
        dict with context-scoped conflict details, or None
    """
    # First check if there's an opposition
    oppositions = detect_opposition(pattern_a.action, pattern_b.action)
    if not oppositions:
        return None

    # Extract context qualifiers
    context_a = extract_context_qualifiers(pattern_a.trigger + " " + pattern_a.action)
    context_b = extract_context_qualifiers(pattern_b.trigger + " " + pattern_b.action)

    # Check if this is a context-scoped conflict
    if not is_context_scoped(pattern_a, pattern_b, context_a, context_b):
        return None

    return {
        "pattern_a": {
            "id": pattern_a.id,
            "trigger": pattern_a.trigger,
            "action": pattern_a.action,
            "confidence": pattern_a.confidence,
            "created_at": pattern_a.created_at.isoformat(),
        },
        "pattern_b": {
            "id": pattern_b.id,
            "trigger": pattern_b.trigger,
            "action": pattern_b.action,
            "confidence": pattern_b.confidence,
            "created_at": pattern_b.created_at.isoformat(),
        },
        "oppositions": oppositions,
        "context_a": sorted(context_a),
        "context_b": sorted(context_b),
        "severity": "info",  # Context-scoped = informational, not a real conflict
        "message": "These patterns have opposing actions but apply to different contexts",
    }


def find_all_conflicts_classified(pattern_a: Pattern, pattern_b: Pattern) -> dict | None:
    """Classify conflicts between two patterns as true or context-scoped.

    Returns a unified conflict dict with a 'type' field:
    - "true_conflict": Same context, opposing actions (needs resolution)
    - "context_scoped": Different contexts, opposing actions (informational)
    - None: No conflict

    Args:
        pattern_a: First pattern
        pattern_b: Second pattern

    Returns:
        Classified conflict dict, or None
    """
    # Check for true conflict first
    true_conflict = find_conflicts(pattern_a, pattern_b)
    if true_conflict:
        true_conflict["type"] = "true_conflict"
        return true_conflict

    # Check for context-scoped conflict
    scoped_conflict = find_context_scoped_conflicts(pattern_a, pattern_b)
    if scoped_conflict:
        scoped_conflict["type"] = "context_scoped"
        return scoped_conflict

    return None


def _normalize(text: str) -> str:
    """Normalize text for comparison."""
    return text.lower().strip()


def _extract_key_terms(text: str) -> set[str]:
    """Extract key terms from a pattern action/trigger for comparison."""
    text = _normalize(text)
    terms = set()
    for word in re.split(r"[\s,;:.!?→←\/\\]+", text):
        word = word.strip(" '\"")
        if len(word) > 1:
            terms.add(word)
    return terms


# Generic terms that should NOT be used for overlap detection
# These appear in many patterns but don't indicate shared domain
GENERIC_TERMS = {
    "when", "the", "use", "instead", "do", "for", "not", "but",
    "and", "or", "if", "in", "on", "at", "to", "from", "with",
    "that", "this", "it", "be", "is", "are", "was", "were",
    "will", "would", "could", "should", "may", "might",
    "can", "must", "shall", "need", "want", "like",
    "make", "set", "get", "run", "write", "writing", "code", "using",
    "pattern", "agent", "user", "always", "never",
}


def _extract_key_terms_filtered(text: str) -> set[str]:
    """Extract key terms, excluding generic terms."""
    return _extract_key_terms(text) - GENERIC_TERMS



def detect_opposition(action_a: str, action_b: str) -> list[dict]:
    """Detect if two actions/patterns suggest opposite behaviors.

    Returns a list of detected oppositions with details.
    """
    oppositions = []
    a_norm = _normalize(action_a)
    b_norm = _normalize(action_b)

    # Check known opposition pairs
    for term_a, term_b in OPPOSITION_PAIRS:
        a_has = term_a in a_norm
        b_has = term_b in b_norm
        a_has_rev = term_b in a_norm
        b_has_rev = term_a in b_norm

        # Conflict: A promotes term_a while B promotes term_b
        # OR: A promotes term_b while B promotes term_a
        if (a_has and b_has) or (a_has_rev and b_has_rev):
            oppositions.append({
                "type": "known_pair",
                "term_a": term_a,
                "term_b": term_b,
                "description": f"'{term_a}' vs '{term_b}'",
            })

    # Check for numeric opposition (e.g., 80% vs 85%)
    nums_a = re.findall(r"(\d+\.?\d*)\s*%", a_norm)
    nums_b = re.findall(r"(\d+\.?\d*)\s*%", b_norm)
    if nums_a and nums_b:
        nums_a_set = set(nums_a)
        nums_b_set = set(nums_b)
        if nums_a_set != nums_b_set:
            oppositions.append({
                "type": "threshold",
                "values_a": nums_a,
                "values_b": nums_b,
                "description": f"Thresholds: {'%'.join(nums_a)}% vs {'%'.join(nums_b)}%",
            })

    return oppositions


def find_conflicts(pattern_a: Pattern, pattern_b: Pattern) -> dict | None:
    """Detect if two patterns are in genuine conflict.

    Two patterns conflict when:
    1. They address similar triggers (same domain/context)
    2. Their actions suggest opposite behaviors

    Returns conflict details dict, or None if no conflict.
    """
    # Check if triggers are in the same domain
    # Use filtered terms to exclude generic words like "when", "use", "do"
    trigger_terms_a = _extract_key_terms_filtered(pattern_a.trigger)
    trigger_terms_b = _extract_key_terms_filtered(pattern_b.trigger)

    # Find common trigger terms (overlap)
    common = trigger_terms_a & trigger_terms_b

    # If triggers share significant overlap, check for action opposition
    if len(common) >= 1:
        oppositions = detect_opposition(pattern_a.action, pattern_b.action)
        if oppositions:
            return {
                "pattern_a": {
                    "id": pattern_a.id,
                    "trigger": pattern_a.trigger,
                    "action": pattern_a.action,
                    "confidence": pattern_a.confidence,
                    "created_at": pattern_a.created_at.isoformat(),
                },
                "pattern_b": {
                    "id": pattern_b.id,
                    "trigger": pattern_b.trigger,
                    "action": pattern_b.action,
                    "confidence": pattern_b.confidence,
                    "created_at": pattern_b.created_at.isoformat(),
                },
                "oppositions": oppositions,
                "shared_context": list(common),
                "severity": "high" if len(oppositions) >= 2 else "medium",
            }

    # Also check if one action directly contradicts the other's trigger context
    action_a_terms = _extract_key_terms(pattern_a.action)
    trigger_b_terms = _extract_key_terms(pattern_b.trigger)
    if action_a_terms & trigger_b_terms:
        oppositions = detect_opposition(pattern_a.action, pattern_b.action)
        if oppositions:
            return {
                "pattern_a": {
                    "id": pattern_a.id,
                    "trigger": pattern_a.trigger,
                    "action": pattern_a.action,
                    "confidence": pattern_a.confidence,
                    "created_at": pattern_a.created_at.isoformat(),
                },
                "pattern_b": {
                    "id": pattern_b.id,
                    "trigger": pattern_b.trigger,
                    "action": pattern_b.action,
                    "confidence": pattern_b.confidence,
                    "created_at": pattern_b.created_at.isoformat(),
                },
                "oppositions": oppositions,
                "shared_context": list(action_a_terms & trigger_b_terms),
                "severity": "high" if len(oppositions) >= 2 else "medium",
            }

    return None


# ── Conflict Resolution Strategies ─────────────────────────────────────

def resolve_confidence_wins(
    storage: Storage, pattern_a_id: str, pattern_b_id: str
) -> dict:
    """Resolve conflict by keeping the higher-confidence pattern.

    The loser gets a confidence penalty (-0.2). If confidence is tied,
    no action is taken.
    """
    pa = storage.get_pattern(pattern_a_id)
    pb = storage.get_pattern(pattern_b_id)
    if not pa or not pb:
        return {"error": "Pattern not found"}

    if pa.confidence == pb.confidence:
        return {"action": "tied", "message": "Both patterns have equal confidence"}

    if pa.confidence > pb.confidence:
        winner, loser = pa, pb
    else:
        winner, loser = pb, pa

    # Penalize loser
    loser.confidence = max(0.0, loser.confidence - 0.2)
    if loser.confidence <= 0.1:
        storage.delete_pattern(loser.id)
        return {
            "action": "resolved_with_removal",
            "winner_id": winner.id,
            "loser_id": loser.id,
            "winner_confidence": winner.confidence,
            "loser_removed": True,
        }

    storage.update_pattern(loser)
    return {
        "action": "resolved",
        "winner_id": winner.id,
        "loser_id": loser.id,
        "winner_confidence": winner.confidence,
        "loser_confidence": loser.confidence,
    }


def resolve_recency_wins(
    storage: Storage, pattern_a_id: str, pattern_b_id: str
) -> dict:
    """Resolve conflict by keeping the newer pattern.

    The older pattern gets a confidence penalty (-0.2).
    """
    pa = storage.get_pattern(pattern_a_id)
    pb = storage.get_pattern(pattern_b_id)
    if not pa or not pb:
        return {"error": "Pattern not found"}

    if pa.created_at >= pb.created_at:
        newer, older = pa, pb
    else:
        newer, older = pb, pa

    # Penalize older pattern
    older.confidence = max(0.0, older.confidence - 0.2)
    if older.confidence <= 0.1:
        storage.delete_pattern(older.id)
        return {
            "action": "resolved_with_removal",
            "winner_id": newer.id,
            "loser_id": older.id,
            "winner_confidence": newer.confidence,
            "loser_removed": True,
        }

    storage.update_pattern(older)
    return {
        "action": "resolved",
        "winner_id": newer.id,
        "loser_id": older.id,
        "winner_confidence": newer.confidence,
        "loser_confidence": older.confidence,
    }


def resolve_suppress_loser(
    storage: Storage, pattern_a_id: str, pattern_b_id: str, loser_id: str
) -> dict:
    """Manually resolve a conflict by suppressing a specific pattern.

    The specified loser gets a confidence penalty (-0.3).
    """
    pa = storage.get_pattern(pattern_a_id)
    pb = storage.get_pattern(pattern_b_id)
    if not pa or not pb:
        return {"error": "Pattern not found"}

    if loser_id == pattern_a_id:
        loser, winner = pa, pb
    elif loser_id == pattern_b_id:
        loser, winner = pb, pa
    else:
        return {"error": "loser_id must be one of the conflicting patterns"}

    loser.confidence = max(0.0, loser.confidence - 0.3)
    if loser.confidence <= 0.1:
        storage.delete_pattern(loser.id)
        return {
            "action": "resolved_with_removal",
            "winner_id": winner.id,
            "loser_id": loser.id,
            "winner_confidence": winner.confidence,
            "loser_removed": True,
        }

    storage.update_pattern(loser)
    return {
        "action": "resolved",
        "winner_id": winner.id,
        "loser_id": loser.id,
        "winner_confidence": winner.confidence,
        "loser_confidence": loser.confidence,
    }


def correction_score(text: str) -> float:
    """Calculate a confidence score that a message is a correction (0.0 - 1.0).
    
    Uses multiple signals and returns a weighted score.
    """
    text_lower = text.lower().strip()
    score = 0.0
    
    # Count matching signals
    matches = 0
    for pattern in CORRECTION_SIGNALS:
        if re.search(pattern, text_lower):
            matches += 1
    
    # Base score from signal count
    if matches == 0:
        score = 0.0
    elif matches == 1:
        score = 0.3
    elif matches == 2:
        score = 0.6
    else:
        score = min(0.9, 0.6 + (matches - 2) * 0.1)
    
    # Boost for explicit correction phrases
    explicit_phrases = [
        "instead", "actually", "no,", "don't", "never", "always use",
        "from now on", "remember", "stop", "fix", "change", "replace",
    ]
    for phrase in explicit_phrases:
        if phrase in text_lower:
            score = min(1.0, score + 0.15)
            break
    
    # Penalty for questions (likely not corrections)
    if re.search(r"\?$", text_lower):
        score *= 0.5
    
    # Penalty for very short messages
    if len(text_lower.split()) < 3:
        score *= 0.7
    
    return round(score, 2)


def correction_score_v2(text: str) -> float:
    """Improved correction detection using structural analysis.
    
    Enhances the original score with:
    - Structural patterns (X not Y, use X instead of Y)
    - Specificity detection (numbers, thresholds, tool names)
    - Contrast markers (but, however, although)
    - Quote detection (users quoting agent output)
    """
    # Start with base score
    base = correction_score(text)
    text_lower = text.lower().strip()
    boost = 0.0

    # ── Structural patterns ──
    # "X not Y" or "not X but Y"
    if re.search(r"\bnot\s+\w+\s+but\b", text_lower):
        boost += 0.2
    # "use X not Y"
    if re.search(r"\buse\s+\w+\s+not\b", text_lower):
        boost += 0.2
    # "X instead of Y"
    if re.search(r"\binstead of\b", text_lower):
        boost += 0.15
    # "rather than"
    if re.search(r"\brather than\b", text_lower):
        boost += 0.15

    # ── Specificity signals ──
    # Contains specific numbers/thresholds
    if re.search(r"\d+%", text_lower):
        boost += 0.1  # Percentage mention
    if re.search(r"\b\d+\s*(px|em|rem|pt)\b", text_lower):
        boost += 0.1  # CSS units
    if re.search(r"\b(vim|emacs|vscode|intellij|pycharm)\b", text_lower):
        boost += 0.1  # Tool names

    # ── Contrast markers ──
    # "but" after a statement (contrast with what agent did)
    if re.search(r"\.\s+but\b", text_lower):
        boost += 0.1
    # "however" or "although"
    if re.search(r"\b(however|although|though)\b", text_lower):
        boost += 0.1

    # ── Quote detection ──
    # User quotes something (likely correcting it)
    if re.search(r'[\"\'].*[\"\']', text_lower):
        boost += 0.1
    # User references specific output
    if re.search(r"\bthe (result|output|answer|response)\b", text_lower):
        boost += 0.05

    # ── Imperative mood ──
    # Commands that sound like corrections
    imperative_starters = [
        "please ", "make sure ", "always ", "never ", "stop ",
        "don't ", "do not ", "use ", "switch to ", "try ",
    ]
    for starter in imperative_starters:
        if text_lower.startswith(starter):
            boost += 0.1
            break

    # ── Multi-sentence corrections ──
    # Longer messages with multiple sentences are more likely corrections
    sentence_count = len(re.split(r"[.!?]+", text_lower))
    if sentence_count >= 3:
        boost += 0.1

    return round(min(1.0, base + boost), 2)


def is_correction(text: str, threshold: float = 0.3) -> bool:
    """Detect if a user message is a correction.
    
    Args:
        text: The user message
        threshold: Minimum score to consider as correction (default 0.3)
    
    Returns:
        True if the message appears to be a correction
    """
    return correction_score(text) >= threshold


def classify_correction(text: str) -> str:
    """Classify a correction into a category."""
    text_lower = text.lower()
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if re.search(kw, text_lower))
        if score > 0:
            scores[category] = score
    if scores:
        return max(scores, key=scores.get)
    return "general"


# ── LLM-Based Correction Detection ─────────────────────────────────────

# Prompt template for LLM classification
CORRECTION_CLASSIFICATION_PROMPT = """You are analyzing a user message to determine if it's a correction to an AI assistant's behavior.

CORRECTION EXAMPLES:
- "No, use const not let" → CORRECTION
- "Actually, the threshold should be 80%" → CORRECTION  
- "Please use TypeScript instead of JavaScript" → CORRECTION
- "Remember to always format code with Prettier" → CORRECTION
- "That's wrong, it should be async/await not .then()" → CORRECTION

NOT CORRECTIONS:
- "What is the best way to handle errors?" → QUESTION
- "Can you help me write a function?" → REQUEST
- "Thanks, that worked!" → FEEDBACK
- "I'm not sure about this approach" → OPINION

USER MESSAGE: "{text}"

Respond with ONLY a JSON object in this exact format:
{{
  "is_correction": true/false,
  "confidence": 0.0-1.0,
  "category": "code_style|threshold|tool_choice|workflow|exclusion|tone|language|general",
  "reasoning": "brief explanation"
}}"""


def correction_score_llm(
    text: str,
    llm_client=None,
    model: str = "gpt-4o-mini",
) -> dict:
    """Classify a correction using an LLM for semantic understanding.
    
    Args:
        text: The user message to classify
        llm_client: An OpenAI-compatible client (must have chat.completions.create)
        model: Model to use for classification (default: gpt-4o-mini)
    
    Returns:
        dict with is_correction, confidence, category, reasoning
    """
    if llm_client is None:
        return {
            "is_correction": False,
            "confidence": 0.0,
            "category": "general",
            "reasoning": "No LLM client provided, cannot perform LLM classification",
            "method": "llm",
        }
    
    try:
        prompt = CORRECTION_CLASSIFICATION_PROMPT.format(text=text)
        
        response = llm_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,  # Low temperature for consistent classification
            max_tokens=200,
        )
        
        # Parse response
        content = response.choices[0].message.content.strip()
        
        # Extract JSON from response (handle markdown code blocks)
        import json
        json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            result["method"] = "llm"
            return result
        else:
            return {
                "is_correction": False,
                "confidence": 0.0,
                "category": "general",
                "reasoning": "Failed to parse LLM response",
                "method": "llm",
            }
            
    except Exception as e:
        return {
            "is_correction": False,
            "confidence": 0.0,
            "category": "general",
            "reasoning": f"LLM call failed: {str(e)}",
            "method": "llm_error",
        }


def correction_score_hybrid(
    text: str,
    llm_client=None,
    model: str = "gpt-4o-mini",
    regex_threshold: float = 0.6,
    llm_threshold: float = 0.5,
) -> dict:
    """Hybrid correction detection combining regex and LLM approaches.
    
    Strategy:
    1. Run regex detection first (fast, free)
    2. If regex score is definitive (>0.6 or <0.2), return immediately
    3. If ambiguous (0.2-0.6), use LLM for semantic understanding
    4. Combine scores for final decision
    
    Args:
        text: The user message to classify
        llm_client: An OpenAI-compatible client (optional)
        model: Model to use for LLM classification (default: gpt-4o-mini)
        regex_threshold: Score above which regex is definitive (default: 0.6)
        llm_threshold: Score above which LLM confirms correction (default: 0.5)
    
    Returns:
        dict with is_correction, confidence, category, reasoning, method
    """
    import json
    
    # Step 1: Run regex detection (fast path)
    regex_score = correction_score_v2(text)
    
    # Step 2: Check if regex is definitive
    if regex_score >= regex_threshold:
        return {
            "is_correction": True,
            "confidence": regex_score,
            "category": classify_correction(text),
            "reasoning": f"Regex detection definitive (score: {regex_score})",
            "method": "regex",
        }
    
    if regex_score < 0.2:
        return {
            "is_correction": False,
            "confidence": regex_score,
            "category": classify_correction(text),
            "reasoning": f"Regex detection definitive (score: {regex_score})",
            "method": "regex",
        }
    
    # Step 3: Ambiguous case — use LLM if available
    if llm_client is None:
        # No LLM available, use regex score as-is
        return {
            "is_correction": regex_score >= 0.3,
            "confidence": regex_score,
            "category": classify_correction(text),
            "reasoning": "Ambiguous, no LLM available, using regex",
            "method": "regex_fallback",
        }
    
    # Call LLM for semantic understanding
    llm_result = correction_score_llm(text, llm_client, model)
    
    # Step 4: Combine scores
    if llm_result["method"] == "llm_error":
        # LLM failed, fall back to regex
        return {
            "is_correction": regex_score >= 0.3,
            "confidence": regex_score,
            "category": classify_correction(text),
            "reasoning": f"LLM failed, using regex (score: {regex_score})",
            "method": "regex_fallback",
        }
    
    # Weighted combination: 40% regex + 60% LLM (LLM is more accurate)
    combined_score = (regex_score * 0.4) + (llm_result["confidence"] * 0.6)
    
    # Determine category (prefer LLM's if available)
    category = llm_result.get("category", classify_correction(text))
    if category == "general":
        category = classify_correction(text)
    
    return {
        "is_correction": combined_score >= llm_threshold,
        "confidence": round(combined_score, 3),
        "category": category,
        "reasoning": f"Hybrid: regex={regex_score}, llm={llm_result['confidence']}, combined={combined_score:.3f}",
        "method": "hybrid",
        "regex_score": regex_score,
        "llm_score": llm_result["confidence"],
        "llm_reasoning": llm_result.get("reasoning", ""),
    }


# ── Pattern Extraction ──────────────────────────────────────────────────

def extract_pattern_from_correction(correction: Correction) -> Optional[Pattern]:
    """Try to extract a reusable pattern from a correction."""
    original = correction.original_behavior.strip()
    corrected = correction.corrected_behavior.strip()
    
    # Skip if too vague
    if len(original) < 3 or len(corrected) < 3:
        return None
    
    # Skip if it's clearly a one-off (contains specific filenames, line numbers, etc.)
    if re.search(r"line \d+|file .+\.\w+|column \d+", original.lower()):
        return None
    
    # Build trigger and action
    trigger = f"When the agent would: {original}"
    action = f"Instead, do: {corrected}"
    
    return Pattern(
        trigger=trigger,
        action=action,
        category=correction.category,
        confidence=0.3,  # Initial confidence
        use_count=1,
    )


# ── Confidence Scoring ──────────────────────────────────────────────────

def calculate_confidence(
    base: float = 0.3,
    use_count: int = 1,
    last_used: Optional[datetime] = None,
    last_confirmed: Optional[datetime] = None,
    ceiling: float = EXPLICIT_CONFIRM_CEILING,
) -> float:
    """Calculate pattern confidence score.
    
    Formula: min(ceiling, base * (1 + log(use_count)) * recency_factor)
    
    recency_factor decays over 90 days of non-use.
    Confirmation boosts confidence more than mere use.

    Args:
        base: Base confidence score (default 0.3)
        use_count: Number of times pattern has been used
        last_used: When the pattern was last used
        last_confirmed: When the pattern was last explicitly confirmed
        ceiling: Maximum confidence allowed (default 1.0, use 0.7 for auto-confirm)
    """
    count_factor = 1 + math.log(max(use_count, 1))
    
    # Recency from last use
    recency = 1.0
    if last_used:
        days = (datetime.now(UTC) - last_used).days
        recency = math.exp(-days / 90)
    
    # Confirmation boost
    confirm_boost = 1.0
    if last_confirmed:
        days_since_confirm = (datetime.now(UTC) - last_confirmed).days
        if days_since_confirm < 30:
            confirm_boost = 1.5  # Recently confirmed = high confidence
    
    confidence = min(ceiling, base * count_factor * recency * confirm_boost)
    return round(confidence, 3)


# ── Pattern Engine ──────────────────────────────────────────────────────

class PatternEngine:
    """Core engine for managing patterns and corrections."""
    
    def __init__(self, storage: Storage):
        self.storage = storage
    
    def record_correction(
        self,
        original: str,
        corrected: str,
        context: str = "",
        category: Optional[str] = None,
    ) -> dict:
        """Record a user correction and extract/update patterns.
        
        Returns:
            dict with pattern_id, confidence, is_new_pattern
        """
        # Classify if not provided
        if not category:
            category = classify_correction(f"{original} {corrected}")
        
        # Create correction
        correction = Correction(
            original_behavior=original,
            corrected_behavior=corrected,
            context=context,
            category=category,
        )
        
        # Check if similar pattern exists
        existing = self._find_similar_pattern(original, corrected)
        
        if existing:
            # Update existing pattern
            existing.use_count += 1
            existing.last_used = datetime.now(UTC)
            existing.confidence = calculate_confidence(
                use_count=existing.use_count,
                last_used=existing.last_used,
                last_confirmed=existing.last_confirmed,
            )
            self.storage.update_pattern(existing)
            correction.pattern_id = existing.id
            self.storage.store_correction(correction)

            # Also check for conflicts when updating
            conflicts = self.find_all_conflicts_for(existing)

            return {
                "pattern_id": existing.id,
                "confidence": existing.confidence,
                "is_new_pattern": False,
                "action": "updated",
                "conflicts": conflicts if conflicts else [],
            }
        else:
            # Extract new pattern
            pattern = extract_pattern_from_correction(correction)
            if not pattern:
                # Store correction without a pattern
                self.storage.store_correction(correction)
                return {
                    "pattern_id": None,
                    "confidence": 0.0,
                    "is_new_pattern": False,
                    "action": "correction_recorded_only",
                }

            pattern.last_used = datetime.now(UTC)
            pattern_id = self.storage.store_pattern(pattern)
            correction.pattern_id = pattern_id
            self.storage.store_correction(correction)

            # Check for conflicts with existing patterns
            conflicts = self.find_all_conflicts_for(pattern)

            return {
                "pattern_id": pattern_id,
                "confidence": pattern.confidence,
                "is_new_pattern": True,
                "action": "created",
                "conflicts": conflicts if conflicts else [],
            }
    
    def get_patterns_for_context(
        self,
        context: str,
        limit: int = 5,
        min_confidence: float = 0.3,
    ) -> list[dict]:
        """Get patterns relevant to the current context."""
        # Try semantic search first
        results = self.storage.search_patterns(context, limit=limit)
        
        # Filter by confidence
        filtered = [
            r for r in results
            if r["pattern"]["confidence"] >= min_confidence
        ]
        
        # If not enough results, supplement with category-based listing
        if len(filtered) < limit:
            all_patterns = self.storage.list_patterns(
                min_confidence=min_confidence,
                sort_by="confidence",
                limit=limit - len(filtered),
            )
            seen_ids = {r["pattern"]["id"] for r in filtered}
            for p in all_patterns:
                if p.id not in seen_ids:
                    filtered.append({"pattern": p.to_dict(), "distance": None})
        
        # Update use counts
        for r in filtered[:limit]:
            pattern = self.storage.get_pattern(r["pattern"]["id"])
            if pattern:
                pattern.use_count += 1
                pattern.last_used = datetime.now(UTC)
                pattern.confidence = calculate_confidence(
                    use_count=pattern.use_count,
                    last_used=pattern.last_used,
                    last_confirmed=pattern.last_confirmed,
                )
                self.storage.update_pattern(pattern)
        
        return filtered[:limit]
    
    def confirm_pattern(self, pattern_id: str) -> dict:
        """User explicitly confirms a pattern is correct."""
        pattern = self.storage.get_pattern(pattern_id)
        if not pattern:
            return {"error": "Pattern not found"}
        
        pattern.last_confirmed = datetime.now(UTC)
        pattern.use_count += 1
        pattern.confidence = calculate_confidence(
            use_count=pattern.use_count,
            last_used=pattern.last_used,
            last_confirmed=pattern.last_confirmed,
        )
        self.storage.update_pattern(pattern)
        
        return {
            "pattern_id": pattern_id,
            "confidence": pattern.confidence,
            "action": "confirmed",
        }
    
    def reject_pattern(self, pattern_id: str) -> dict:
        """User explicitly rejects a pattern."""
        pattern = self.storage.get_pattern(pattern_id)
        if not pattern:
            return {"error": "Pattern not found"}
        
        # Reduce confidence significantly
        pattern.confidence = max(0.0, pattern.confidence - 0.3)
        self.storage.update_pattern(pattern)
        
        # If confidence is very low, consider removing
        if pattern.confidence <= 0.1:
            self.storage.delete_pattern(pattern_id)
            return {"removed": True, "pattern_id": pattern_id}
        
        return {
            "pattern_id": pattern_id,
            "confidence": pattern.confidence,
            "action": "rejected",
        }
    
    def _find_similar_pattern(
        self, original: str, corrected: str
    ) -> Optional[Pattern]:
        """Find an existing pattern that matches this correction.

        Uses a two-phase approach:
        1. ChromaDB semantic search on the full query (trigger + action)
        2. Fallback: direct action-text comparison (catches corrections with
           different original text but the same corrected action)

        Returns None if the similar pattern's action opposes the new correction,
        so that opposing corrections create separate patterns (enabling conflict detection).
        """
        new_action = _normalize(f"Instead, do: {corrected}")

        # Phase 1: ChromaDB semantic search
        query = f"When the agent would: {original} → Instead, do: {corrected}"
        results = self.storage.search_patterns(query, limit=1)

        if results and results[0]["distance"] is not None:
            if results[0]["distance"] < 0.4:
                candidate = self.storage.get_pattern(results[0]["pattern"]["id"])
                if candidate:
                    oppositions = detect_opposition(candidate.action, f"Instead, do: {corrected}")
                    if oppositions:
                        return None
                    return candidate

        # Phase 2: Direct action-text comparison (fallback)
        # When corrections have different original text but the same corrected
        # action, ChromaDB embeddings may not match closely enough. Compare
        # the normalized action text directly.
        all_patterns = self.storage.list_patterns(
            min_confidence=0.0, sort_by="confidence", limit=100
        )
        best_match = None
        best_similarity = 0.0

        for pattern in all_patterns:
            existing_action = _normalize(pattern.action)
            # Simple token overlap: if 80%+ of tokens match, treat as same action
            new_tokens = set(re.split(r"[\s,;:.!?→←/\\]+", new_action)) - GENERIC_TERMS
            existing_tokens = set(re.split(r"[\s,;:.!?→←/\\]+", existing_action)) - GENERIC_TERMS
            if not new_tokens or not existing_tokens:
                continue
            overlap = len(new_tokens & existing_tokens) / max(len(new_tokens), len(existing_tokens))
            if overlap >= 0.8 and overlap > best_similarity:
                # Check opposition before accepting
                oppositions = detect_opposition(pattern.action, f"Instead, do: {corrected}")
                if not oppositions:
                    best_match = pattern
                    best_similarity = overlap

        return best_match
    
    def get_stats(self) -> dict:
        """Get engine statistics."""
        return {
            "total_patterns": self.storage.count_patterns(),
            "total_corrections": self.storage.count_corrections(),
            "high_confidence": len(self.storage.list_patterns(min_confidence=0.7)),
            "low_confidence": len(self.storage.list_patterns(min_confidence=0.0, limit=100)),
        }

    def decay_stale_patterns(
        self,
        stale_days: int = 90,
        removal_threshold: float = 0.1,
        dry_run: bool = False,
    ) -> dict:
        """Recalculate confidence for all patterns based on recency, remove very low ones.

        Patterns not used in `stale_days` get their confidence recalculated using
        the existing decay formula. Patterns that decay below `removal_threshold`
        are deleted.

        Args:
            stale_days: Days of non-use before decay kicks in (default: 90)
            removal_threshold: Confidence below which patterns are removed (default: 0.1)
            dry_run: If True, report what would happen without making changes

        Returns:
            dict with decay statistics
        """
        all_patterns = self.storage.list_patterns(
            min_confidence=0.0, sort_by="recent", limit=1000
        )

        now = datetime.now(UTC)
        decayed = 0
        removed = 0
        kept = 0
        removal_candidates = []

        for pattern in all_patterns:
            # Calculate days since last use
            last_use = pattern.last_used or pattern.created_at
            days_idle = (now - last_use).days

            if days_idle < stale_days:
                kept += 1
                continue

            # Recalculate confidence with decay
            new_confidence = calculate_confidence(
                base=0.3,
                use_count=pattern.use_count,
                last_used=pattern.last_used,
                last_confirmed=pattern.last_confirmed,
            )

            if new_confidence < pattern.confidence:
                decayed += 1

            if new_confidence <= removal_threshold:
                removed += 1
                removal_candidates.append({
                    "id": pattern.id,
                    "action": pattern.action,
                    "old_confidence": pattern.confidence,
                    "new_confidence": new_confidence,
                    "days_idle": days_idle,
                })
                if not dry_run:
                    self.storage.delete_pattern(pattern.id)
            else:
                kept += 1
                if not dry_run:
                    pattern.confidence = new_confidence
                    self.storage.update_pattern(pattern)

        return {
            "dry_run": dry_run,
            "total_scanned": len(all_patterns),
            "decayed": decayed,
            "removed": removed,
            "kept": kept,
            "removal_candidates": removal_candidates,
        }

    def get_decay_preview(self, stale_days: int = 90, removal_threshold: float = 0.1) -> dict:
        """Preview what decay_stale_patterns would do without making changes."""
        return self.decay_stale_patterns(
            stale_days=stale_days,
            removal_threshold=removal_threshold,
            dry_run=True,
        )

    # ── Auto-Confirmation ──────────────────────────────────────────────

    def mark_pattern_applied(self, pattern_id: str) -> dict:
        """Mark a pattern as applied (retrieved via check_before_acting or get_session_context).
        
        This tracks when patterns are used so we can auto-confirm them
        after repeated successful applications without correction.
        
        Args:
            pattern_id: The pattern ID that was applied
        Returns:
            dict with pattern_id, applied_count, and auto_confirm_status
        """
        pattern = self.storage.get_pattern(pattern_id)
        if not pattern:
            return {"error": "Pattern not found"}

        pattern.applied_count += 1
        pattern.last_applied = datetime.now(UTC)
        pattern.use_count += 1
        pattern.last_used = datetime.now(UTC)

        # Recalculate confidence with the new use
        pattern.confidence = calculate_confidence(
            use_count=pattern.use_count,
            last_used=pattern.last_used,
            last_confirmed=pattern.last_confirmed,
        )

        self.storage.update_pattern(pattern)

        return {
            "pattern_id": pattern_id,
            "applied_count": pattern.applied_count,
            "confidence": pattern.confidence,
            "auto_confirmed": pattern.auto_confirmed,
        }

    def auto_confirm_pattern(
        self,
        pattern_id: str,
        min_applications: int = 3,
    ) -> dict:
        """Auto-confirm a pattern after repeated successful applications.
        
        When a pattern has been applied multiple times without the user
        correcting it, we can boost its confidence automatically. This
        reduces the need for explicit confirmation.
        
        Args:
            pattern_id: The pattern ID to auto-confirm
            min_applications: Minimum applications before auto-confirming (default: 3)
        Returns:
            dict with pattern_id, confidence, action taken
        """
        pattern = self.storage.get_pattern(pattern_id)
        if not pattern:
            return {"error": "Pattern not found"}

        # Check if already auto-confirmed
        if pattern.auto_confirmed:
            return {
                "pattern_id": pattern_id,
                "confidence": pattern.confidence,
                "action": "already_auto_confirmed",
            }

        # Check if enough applications
        if pattern.applied_count < min_applications:
            return {
                "pattern_id": pattern_id,
                "applied_count": pattern.applied_count,
                "min_required": min_applications,
                "action": "insufficient_applications",
            }

        # Check if there were any corrections after the last application
        # (if user corrected, we shouldn't auto-confirm)
        if pattern.last_applied:
            corrections_after = self.storage.get_recent_corrections(limit=10)
            for correction in corrections_after:
                if (correction.pattern_id == pattern_id and
                    correction.timestamp > pattern.last_applied):
                    # User corrected after the pattern was applied
                    return {
                        "pattern_id": pattern_id,
                        "action": "corrected_after_application",
                        "correction_time": correction.timestamp.isoformat(),
                    }

        # Auto-confirm!
        pattern.auto_confirmed = True
        pattern.last_confirmed = datetime.now(UTC)
        pattern.confidence = calculate_confidence(
            use_count=pattern.use_count,
            last_used=pattern.last_used,
            last_confirmed=pattern.last_confirmed,
            ceiling=AUTO_CONFIRM_CEILING,
        )
        self.storage.update_pattern(pattern)

        return {
            "pattern_id": pattern_id,
            "confidence": pattern.confidence,
            "applied_count": pattern.applied_count,
            "action": "auto_confirmed",
        }

    def get_auto_confirmable_patterns(
        self,
        min_applications: int = 3,
    ) -> list[dict]:
        """Get patterns that are eligible for auto-confirmation.
        
        Returns patterns that have been applied enough times but not yet
        auto-confirmed, and haven't been corrected after their last application.
        
        Args:
            min_applications: Minimum applications required (default: 3)
        Returns:
            List of patterns eligible for auto-confirmation
        """
        all_patterns = self.storage.list_patterns(
            min_confidence=0.0, sort_by="confidence", limit=1000
        )

        candidates = []
        for pattern in all_patterns:
            # Skip already auto-confirmed
            if pattern.auto_confirmed:
                continue

            # Skip if not enough applications
            if pattern.applied_count < min_applications:
                continue

            # Check if corrected after last application
            if pattern.last_applied:
                corrections = self.storage.get_recent_corrections(limit=10)
                corrected_after = False
                for correction in corrections:
                    if (correction.pattern_id == pattern.id and
                        correction.timestamp > pattern.last_applied):
                        corrected_after = True
                        break
                if corrected_after:
                    continue

            candidates.append({
                "pattern_id": pattern.id,
                "action": pattern.action,
                "confidence": pattern.confidence,
                "applied_count": pattern.applied_count,
                "last_applied": pattern.last_applied.isoformat() if pattern.last_applied else None,
            })

        return candidates

    def get_correction_after_application(
        self,
        pattern_id: str,
        since: Optional[datetime] = None,
    ) -> Optional[dict]:
        """Check if a pattern was corrected after being applied.

        Args:
            pattern_id: The pattern ID to check
            since: Only check corrections after this time

        Returns:
            Correction info if found, None otherwise
        """
        pattern = self.storage.get_pattern(pattern_id)
        if not pattern or not pattern.last_applied:
            return None

        check_since = since or pattern.last_applied
        corrections = self.storage.get_recent_corrections(limit=50)

        for correction in corrections:
            if (correction.pattern_id == pattern_id and
                correction.timestamp > check_since):
                return {
                    "correction_id": correction.id,
                    "original": correction.original_behavior,
                    "corrected": correction.corrected_behavior,
                    "timestamp": correction.timestamp.isoformat(),
                }

        return None

    # ── Pattern Conflicts ─────────────────────────────────────────────

    def find_all_conflicts_for(self, pattern: Pattern) -> list[dict]:
        """Find all patterns that conflict with the given pattern.

        Args:
            pattern: The pattern to check for conflicts

        Returns:
            List of conflict details dicts
        """
        all_patterns = self.storage.list_patterns(
            min_confidence=0.0, sort_by="confidence", limit=1000
        )

        conflicts = []
        for other in all_patterns:
            if other.id == pattern.id:
                continue
            conflict = find_conflicts(pattern, other)
            if conflict:
                conflicts.append(conflict)

        return conflicts

    def get_all_conflicts(self) -> list[dict]:
        """Find all conflicts across all stored patterns.

        Returns:
            List of conflict details, deduplicated.
        """
        all_patterns = self.storage.list_patterns(
            min_confidence=0.0, sort_by="confidence", limit=1000
        )

        seen_pairs = set()
        conflicts = []

        for i, pa in enumerate(all_patterns):
            for pb in all_patterns[i + 1:]:
                pair_key = tuple(sorted([pa.id, pb.id]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                conflict = find_conflicts(pa, pb)
                if conflict:
                    conflicts.append(conflict)

        return conflicts

    def resolve_conflict(
        self,
        pattern_a_id: str,
        pattern_b_id: str,
        strategy: str = "confidence",
        loser_id: Optional[str] = None,
    ) -> dict:
        """Resolve a conflict between two patterns.

        Strategies:
        - "confidence": Higher confidence wins, loser penalized (-0.2)
        - "recency": Newer pattern wins, older penalized (-0.2)
        - "suppress": Manually suppress the pattern specified by loser_id

        Args:
            pattern_a_id: First pattern ID
            pattern_b_id: Second pattern ID
            strategy: Resolution strategy (default: "confidence")
            loser_id: For "suppress" strategy, which pattern to penalize

        Returns:
            Resolution result dict
        """
        if strategy == "confidence":
            return resolve_confidence_wins(self.storage, pattern_a_id, pattern_b_id)
        elif strategy == "recency":
            return resolve_recency_wins(self.storage, pattern_a_id, pattern_b_id)
        elif strategy == "suppress":
            if not loser_id:
                return {"error": "loser_id required for suppress strategy"}
            return resolve_suppress_loser(self.storage, pattern_a_id, pattern_b_id, loser_id)
        else:
            return {"error": f"Unknown strategy: {strategy}. Use confidence, recency, or suppress."}

    # ── Context-Scoped Conflicts ──────────────────────────────────────

    def get_all_context_scoped_conflicts(self) -> list[dict]:
        """Find all context-scoped conflicts across all stored patterns.

        Context-scoped conflicts are patterns with opposing actions
        that apply to different contexts (e.g., "use const in React"
        vs "use let in Node"). These are informational, not true conflicts.

        Returns:
            List of context-scoped conflict details, deduplicated.
        """
        all_patterns = self.storage.list_patterns(
            min_confidence=0.0, sort_by="confidence", limit=1000
        )

        seen_pairs = set()
        conflicts = []

        for i, pa in enumerate(all_patterns):
            for pb in all_patterns[i + 1:]:
                pair_key = tuple(sorted([pa.id, pb.id]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                conflict = find_context_scoped_conflicts(pa, pb)
                if conflict:
                    conflicts.append(conflict)

        return conflicts

    def get_all_conflicts_classified(self) -> list[dict]:
        """Find all conflicts (true + context-scoped) with classification.

        Returns a unified list where each conflict has a 'type' field:
        - "true_conflict": Same context, opposing actions (needs resolution)
        - "context_scoped": Different contexts, opposing actions (informational)

        Returns:
            List of classified conflict details, deduplicated.
        """
        all_patterns = self.storage.list_patterns(
            min_confidence=0.0, sort_by="confidence", limit=1000
        )

        seen_pairs = set()
        conflicts = []

        for i, pa in enumerate(all_patterns):
            for pb in all_patterns[i + 1:]:
                pair_key = tuple(sorted([pa.id, pb.id]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                conflict = find_all_conflicts_classified(pa, pb)
                if conflict:
                    conflicts.append(conflict)

        return conflicts

    # ── Context-Aware Auto-Apply ──────────────────────────────────────

    def get_applicable_patterns(
        self,
        context: str,
        action_type: str = "",
        min_confidence: float = 0.7,
        limit: int = 10,
    ) -> list[dict]:
        """Find patterns eligible for auto-apply based on context.

        Returns patterns with confidence >= min_confidence that match
        the given context. These patterns are trusted enough to be
        applied automatically without asking the user.

        Args:
            context: Description of the current task or context
            action_type: What the agent is about to do (optional filter)
            min_confidence: Minimum confidence threshold (default: 0.7)
            limit: Maximum patterns to return (default: 10)

        Returns:
            List of pattern dicts eligible for auto-apply
        """
        query = f"{action_type} {context}".strip()
        results = self.storage.search_patterns(query, limit=limit * 2)

        applicable = []
        for r in results:
            p = r["pattern"]
            if p["confidence"] < min_confidence:
                continue
            applicable.append({
                "pattern_id": p["id"],
                "trigger": p["trigger"],
                "action": p["action"],
                "category": p["category"],
                "confidence": p["confidence"],
                "distance": r.get("distance"),
                "use_count": p.get("use_count", 0),
                "auto_confirmed": p.get("auto_confirmed", False),
            })
            if len(applicable) >= limit:
                break

        return applicable

    def auto_apply_patterns(
        self,
        context: str,
        action_type: str = "",
        min_confidence: float = 0.7,
        limit: int = 5,
        dry_run: bool = False,
    ) -> dict:
        """Automatically apply high-confidence patterns for a context.

        Finds patterns that match the context and have high enough
        confidence to be applied without user confirmation. Marks them
        as applied (tracking for auto-confirmation).

        Args:
            context: Description of the current task or context
            action_type: What the agent is about to do (optional)
            min_confidence: Minimum confidence for auto-apply (default: 0.7)
            limit: Max patterns to apply (default: 5)
            dry_run: If True, return what would be applied without changes

        Returns:
            dict with applied patterns, skipped patterns, and dry_run flag
        """
        applicable = self.get_applicable_patterns(
            context=context,
            action_type=action_type,
            min_confidence=min_confidence,
            limit=limit,
        )

        applied = []
        skipped = []

        for item in applicable:
            pattern = self.storage.get_pattern(item["pattern_id"])
            if not pattern:
                continue

            # Check for true conflicts with higher-confidence patterns
            has_conflict = False
            all_patterns = self.storage.list_patterns(
                min_confidence=0.0, sort_by="confidence", limit=100
            )
            for other in all_patterns:
                if other.id == pattern.id:
                    continue
                if other.confidence <= pattern.confidence:
                    continue
                conflict = find_conflicts(pattern, other)
                if conflict:
                    has_conflict = True
                    skipped.append({
                        "pattern_id": pattern.id,
                        "action": pattern.action,
                        "confidence": pattern.confidence,
                        "reason": "conflict_with_higher_confidence",
                        "conflicting_with": other.id,
                    })
                    break

            if has_conflict:
                continue

            if not dry_run:
                self.mark_pattern_applied(pattern.id)

            applied.append({
                "pattern_id": pattern.id,
                "action": pattern.action,
                "category": pattern.category,
                "confidence": pattern.confidence,
            })

        return {
            "dry_run": dry_run,
            "context": context,
            "action_type": action_type,
            "applied": applied,
            "skipped": skipped,
            "total_applied": len(applied),
            "total_skipped": len(skipped),
        }
