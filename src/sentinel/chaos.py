"""Chaos/failure injection layer for Sentinel.

Provides deterministic, budgeted failure injection for tool calls and LLM
responses, enabling resilience testing of agents under realistic failure
conditions.

Components:
    - ToolFailureInjector: injects failures into specific mock tool calls
    - LLMFailureInjector: injects failures at the LLM/step level
    - ChaosBudget: enforces a cap on total failures per test run
    - InjectionRecord: logs every injection for post-hoc assertion

Usage:
    from sentinel.chaos import ChaosBudget, ToolFailureInjector, LLMFailureInjector

    chaos = (ChaosBudget(max_failures=3)
        .add(ToolFailureInjector(
            tool_name="search",
            failure_type="timeout",
            probability=0.1,
            seed=42
        ))
        .add(LLMFailureInjector(
            failure_type="rate_limit",
            after_step=3
        )))
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from sentinel.env import (
    MockTool,
    MockToolCall,
    MockToolError,
    RateLimitError,
    TimeoutError,
)
from sentinel.models import AgentTrace, Step, StateChange

import copy
import hashlib
# ──────────────────────────────────────────────────────
# Failure type enumerations
# ──────────────────────────────────────────────────────


class ToolFailureType(str, Enum):
    """Types of failures that can be injected into tool calls."""

    TIMEOUT = "timeout"
    ERROR = "error"
    RATE_LIMIT = "rate_limit"
    MALFORMED = "malformed"
    PARTIAL = "partial"


class LLMFailureType(str, Enum):
    """Types of failures that can be injected at the LLM/step level."""

    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    PARTIAL_RESPONSE = "partial_response"
    STREAM_INTERRUPT = "stream_interrupt"


# ──────────────────────────────────────────────────────
# Context degradation types
# ──────────────────────────────────────────────────────


__all__ = [
    # Enums
    "DegradationStrategy",
    "DriftIntensity",
    # Injectors
    "ToolFailureInjector",
    "LLMFailureInjector",
    "ContextDegradation",
    "SpecDrift",
    "CascadingFailures",
    "ChaosBudget",
    "ChaosBudgetExhausted",
]


class DegradationStrategy(str, Enum):
    """Strategies for context degradation simulation."""

    # Truncate earlier context as steps accumulate (simulates window pressure)
    TRUNCATION = "truncation"
    # Inject noise into tool results (simulates signal degradation)
    NOISE = "noise"
    # Gradually shift instructions (simulates instruction drift)
    DRIFT = "drift"


class DriftIntensity(str, Enum):
    """Intensity levels for SpecDrift injection."""

    SUBTLE = "subtle"  # Minor deviations, hard to detect
    MODERATE = "moderate"  # Noticeable but still functional
    AGGRESSIVE = "aggressive"  # Clear spec deviation


# ──────────────────────────────────────────────────────
# Injection record — audit trail
# ──────────────────────────────────────────────────────


@dataclass
class InjectionRecord:
    """Record of a single injected failure.

    Captures what failed, when, and why for later assertion and debugging.
    """

    injector_type: str  # "tool" or "llm"
    failure_type: str
    target: str  # tool name or step description
    step_id: Optional[int] = None
    call_index: Optional[int] = None
    timestamp: float = field(default_factory=time.time)
    message: str = ""


# ──────────────────────────────────────────────────────
# Failure injector protocol
# ──────────────────────────────────────────────────────


@runtime_checkable
class FailureInjector(Protocol):
    """Protocol that all failure injectors must implement."""

    @property
    def injection_count(self) -> int:
        """Number of failures injected so far."""
        ...

    @property
    def records(self) -> List[InjectionRecord]:
        """List of injection records for this injector."""
        ...

    def reset(self) -> None:
        """Reset injection state (clear history)."""
        ...


# ──────────────────────────────────────────────────────
# ChaosToolWrapper — callable proxy for injected tools
# ──────────────────────────────────────────────────────


class ChaosToolWrapper:
    """Callable wrapper that intercepts tool calls for failure injection.

    Since Python's special method lookup for ``__call__`` goes to the type
    (not the instance), we cannot monkey-patch ``tool.__call__``. Instead,
    ``ToolFailureInjector.wrap()`` returns one of these wrappers that the
    test harness uses in place of the raw MockTool.

    The wrapper delegates to the original tool when no injection occurs,
    preserving call recording and response behavior.
    """

    def __init__(
        self,
        tool: MockTool,
        injector: ToolFailureInjector,
    ) -> None:
        self._tool = tool
        self._injector = injector

    def __call__(self, **kwargs: Any) -> Any:
        if self._injector.tool_name and self._tool.name != self._injector.tool_name:
            return self._tool(**kwargs)

        if self._injector._should_inject():
            error = self._injector._create_failure(kwargs)
            self._injector._injection_count += 1
            record = InjectionRecord(
                injector_type="tool",
                failure_type=self._injector.failure_type.value,
                target=self._tool.name,
                call_index=self._injector._call_count,
                message=str(error),
            )
            self._injector._records.append(record)
            raise error

        return self._tool(**kwargs)

    @property
    def tool(self) -> MockTool:
        """Access the underlying MockTool."""
        return self._tool

    @property
    def name(self) -> str:
        return self._tool.name

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to the underlying tool.

        Only called when normal attribute lookup fails (i.e. not found on
        the instance or class), so ``self._tool``, ``self._injector``,
        and ``self.tool`` (property) are resolved normally.
        """
        return getattr(self._tool, name)


# ──────────────────────────────────────────────────────
# ToolFailureInjector
# ──────────────────────────────────────────────────────


class ToolFailureInjector:
    """Injects failures into specific mock tool calls.

    Supports probability-based injection (fail X% of calls) and
    deterministic seeding for reproducibility. Use ``wrap()`` to get
    a callable wrapper that intercepts calls to a MockTool.

    Args:
        tool_name: Name of the tool to target.
        failure_type: Type of failure to inject (see ToolFailureType).
        probability: Probability of failure on each call (0.0–1.0).
                     Default 1.0 = fail every call.
        seed: Random seed for deterministic failure injection.
        after_step: If set, only inject after this many tool calls.
        error_message: Custom error message for the injected failure.
    """

    def __init__(
        self,
        tool_name: str,
        failure_type: str = "error",
        probability: float = 1.0,
        seed: Optional[int] = None,
        after_step: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        self.tool_name = tool_name
        self.failure_type = ToolFailureType(failure_type)
        self.probability = probability
        self._rng = random.Random(seed)
        self.after_step = after_step
        self.error_message = error_message

        self._injection_count: int = 0
        self._call_count: int = 0
        self._records: List[InjectionRecord] = []

    @property
    def injection_count(self) -> int:
        """Number of failures injected so far."""
        return self._injection_count

    @property
    def records(self) -> List[InjectionRecord]:
        """List of injection records for this injector."""
        return list(self._records)

    def reset(self) -> None:
        """Reset injection state."""
        self._injection_count = 0
        self._call_count = 0
        self._records.clear()

    def _should_inject(self) -> bool:
        """Decide whether this call should fail."""
        self._call_count += 1
        if self._call_count <= self.after_step:
            return False
        return self._rng.random() < self.probability

    def _create_failure(self, arguments: Dict[str, Any]) -> Exception:
        """Create the appropriate exception for the configured failure type."""
        msg = self.error_message or self._default_message()

        if self.failure_type == ToolFailureType.TIMEOUT:
            return TimeoutError(msg)
        elif self.failure_type == ToolFailureType.RATE_LIMIT:
            return RateLimitError(msg)
        elif self.failure_type == ToolFailureType.ERROR:
            return MockToolError(msg)
        elif self.failure_type == ToolFailureType.MALFORMED:
            return MockToolError(
                "Malformed response: invalid data format",
                status_code=502,
            )
        elif self.failure_type == ToolFailureType.PARTIAL:
            return MockToolError(
                "Partial response: connection closed mid-transfer",
                status_code=200,
            )
        else:
            return MockToolError(msg)

    def _default_message(self) -> str:
        """Generate a default error message for the failure type."""
        messages = {
            ToolFailureType.TIMEOUT: "Request timed out after 30s",
            ToolFailureType.ERROR: "Internal server error",
            ToolFailureType.RATE_LIMIT: "Rate limit exceeded (429)",
            ToolFailureType.MALFORMED: "Malformed response from API",
            ToolFailureType.PARTIAL: "Partial response received",
        }
        return messages.get(self.failure_type, "Unknown error")

    def wrap(self, tool: MockTool) -> MockTool:
        """Wrap a MockTool with failure injection.

        Installs a ``call_handler`` on the tool so that ``tool(**kwargs)``
        goes through the injector's decision logic.  The original tool is
        modified **in place** and also returned for convenience::

            injector = ToolFailureInjector(tool_name="search", failure_type="timeout")
            tool = MockTool("search", response="results")
            injector.wrap(tool)  # tool itself is now wrapped

            result = tool(q="query")  # may raise TimeoutError
        """
        original_response = tool.response
        original_response_fn = tool.response_fn

        def _injected_call(**kwargs: Any) -> Any:
            # Record the call on the underlying tool
            from sentinel.env import MockToolCall
            import time as _time
            call = MockToolCall(tool_name=tool.name, arguments=kwargs)
            tool.calls.append(call)
            start = _time.time()

            if self.tool_name and tool.name != self.tool_name:
                # Not targeting this tool — delegate to original
                if original_response_fn is not None:
                    result = original_response_fn(**kwargs)
                else:
                    result = original_response
                call.result = result
                call.duration_ms = (_time.time() - start) * 1000
                return result

            if self._should_inject():
                error = self._create_failure(kwargs)
                self._injection_count += 1
                record = InjectionRecord(
                    injector_type="tool",
                    failure_type=self.failure_type.value,
                    target=tool.name,
                    call_index=self._call_count,
                    message=str(error),
                )
                self._records.append(record)
                call.error = str(error)
                call.duration_ms = (_time.time() - start) * 1000
                raise error

            # Pass through to original behavior
            if original_response_fn is not None:
                result = original_response_fn(**kwargs)
            else:
                result = original_response
            call.result = result
            call.duration_ms = (_time.time() - start) * 1000
            return result

        tool.call_handler = _injected_call
        return tool

    def inject(
        self,
        tool: MockTool,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Manually trigger injection check on a tool call.

        Returns True if an injection was performed, False otherwise.
        This is the lower-level API for explicit injection control.
        """
        if tool.name != self.tool_name:
            return False

        if not self._should_inject():
            return False

        error = self._create_failure(arguments or {})
        self._injection_count += 1
        record = InjectionRecord(
            injector_type="tool",
            failure_type=self.failure_type.value,
            target=tool.name,
            call_index=self._call_count,
            message=str(error),
        )
        self._records.append(record)
        raise error


# ──────────────────────────────────────────────────────
# LLMFailureInjector
# ──────────────────────────────────────────────────────


class LLMFailureInjector:
    """Injects failures at the LLM/step level.

    Simulates failures that occur in the LLM layer rather than tool calls:
    rate limits, timeouts, partial responses, and stream interruptions.

    These injectors are evaluated per-step and return a failure response
    that the test harness can inject into the agent's step output.

    Args:
        failure_type: Type of LLM failure (see LLMFailureType).
        after_step: Only inject after this many steps have executed.
        probability: Probability of failure on each eligible step.
        seed: Random seed for deterministic injection.
        error_message: Custom error message.
    """

    def __init__(
        self,
        failure_type: str = "rate_limit",
        after_step: int = 0,
        probability: float = 1.0,
        seed: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        self.failure_type = LLMFailureType(failure_type)
        self.after_step = after_step
        self.probability = probability
        self._rng = random.Random(seed)
        self.error_message = error_message

        self._injection_count: int = 0
        self._step_count: int = 0
        self._records: List[InjectionRecord] = []

    @property
    def injection_count(self) -> int:
        """Number of failures injected so far."""
        return self._injection_count

    @property
    def records(self) -> List[InjectionRecord]:
        """List of injection records for this injector."""
        return list(self._records)

    def reset(self) -> None:
        """Reset injection state."""
        self._injection_count = 0
        self._step_count = 0
        self._records.clear()

    def _should_inject(self) -> bool:
        """Decide whether this step should fail."""
        self._step_count += 1
        if self._step_count <= self.after_step:
            return False
        return self._rng.random() < self.probability

    def check_step(self, step_id: int) -> Optional[Dict[str, Any]]:
        """Check whether a step should be injected with a failure.

        Returns a failure dict if injection should occur, None otherwise.
        The failure dict contains the type and message for the test harness
        to use when constructing the agent's response.
        """
        if not self._should_inject():
            return None

        self._injection_count += 1
        msg = self.error_message or self._default_message()
        record = InjectionRecord(
            injector_type="llm",
            failure_type=self.failure_type.value,
            target=f"step_{step_id}",
            step_id=step_id,
            message=msg,
        )
        self._records.append(record)

        return {
            "type": self.failure_type.value,
            "message": msg,
            "step_id": step_id,
            "injector": "llm",
        }

    def get_error(self, step_id: int) -> Optional[Exception]:
        """Get the appropriate exception for an LLM failure at the given step.

        Returns the exception if injection should occur, None otherwise.
        """
        failure = self.check_step(step_id)
        if failure is None:
            return None

        msg = failure["message"]
        ft = self.failure_type

        if ft == LLMFailureType.RATE_LIMIT:
            return RateLimitError(msg)
        elif ft == LLMFailureType.TIMEOUT:
            return TimeoutError(msg)
        elif ft == LLMFailureType.PARTIAL_RESPONSE:
            return MockToolError(
                "Partial LLM response: stream ended prematurely",
                status_code=200,
            )
        elif ft == LLMFailureType.STREAM_INTERRUPT:
            return MockToolError(
                "Stream interrupted: connection lost during generation",
                status_code=500,
            )
        else:
            return MockToolError(msg)

    def _default_message(self) -> str:
        """Generate a default error message for the failure type."""
        messages = {
            LLMFailureType.RATE_LIMIT: "LLM API rate limit exceeded",
            LLMFailureType.TIMEOUT: "LLM API request timed out",
            LLMFailureType.PARTIAL_RESPONSE: "LLM returned partial response",
            LLMFailureType.STREAM_INTERRUPT: "LLM stream was interrupted",
        }
        return messages.get(self.failure_type, "Unknown LLM error")


# ──────────────────────────────────────────────────────
# ContextDegradation — simulates long-running task erosion
# ──────────────────────────────────────────────────────


class ContextDegradation:
    """Simulates context window erosion during long-running agent tasks.

    As agents execute more steps, their effective context degrades —
    earlier instructions get truncated, tool results accumulate noise,
    or the system prompt drifts from its original intent. This injector
    models that degradation deterministically.

    Three strategies:
      - TRUNCATION: progressively removes earlier context entries
      - NOISE: injects random perturbations into tool results
      - DRIFT: gradually shifts system prompt instructions

    Args:
        strategy: Degradation strategy to use.
        start_step: Step at which degradation begins (default 1 = immediate).
        degradation_rate: How fast degradation accelerates per step (0.0-1.0).
                          0.1 = mild erosion, 0.5 = aggressive, 1.0 = instant.
        seed: Random seed for deterministic noise injection.
        max_truncation_pct: Maximum fraction of context to truncate (0.0-1.0).
    """

    def __init__(
        self,
        strategy: str = "truncation",
        start_step: int = 1,
        degradation_rate: float = 0.1,
        seed: Optional[int] = None,
        max_truncation_pct: float = 0.5,
    ) -> None:
        self.strategy = DegradationStrategy(strategy)
        self.start_step = start_step
        self.degradation_rate = max(0.0, min(1.0, degradation_rate))
        self._rng = random.Random(seed)
        self.max_truncation_pct = max_truncation_pct

        self._step_count: int = 0
        self._injection_count: int = 0
        self._records: List[InjectionRecord] = []
        # Drift offsets accumulate over time — the longer the run, the more
        # the instructions diverge from the original spec.
        self._drift_accumulator: float = 0.0

    @property
    def injection_count(self) -> int:
        return self._injection_count

    @property
    def records(self) -> List[InjectionRecord]:
        return list(self._records)

    @property
    def current_degradation_level(self) -> float:
        """Current degradation intensity (0.0 = none, 1.0 = maximum).

        Uses an accelerating curve: degradation gets worse faster as
        steps accumulate, simulating real context window pressure where
        the last 20% of context is much worse than the first 20%.
        """
        if self._step_count <= self.start_step:
            return 0.0
        elapsed = self._step_count - self.start_step
        # Quadratic acceleration — degradation compounds
        raw = elapsed * self.degradation_rate
        return min(1.0, raw * raw)

    def reset(self) -> None:
        self._step_count = 0
        self._injection_count = 0
        self._records.clear()
        self._drift_accumulator = 0.0

    def on_step(
        self,
        step_id: int,
        context: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a step and return degraded context/prompt.

        Args:
            step_id: Current step number.
            context: List of context entries (messages, tool results, etc.).
                     Each entry is a dict with at least 'role' and 'content'.
            system_prompt: The system prompt string (modified for DRIFT strategy).

        Returns:
            Dict with keys matching the input:
              - 'context': possibly truncated/noised context list
              - 'system_prompt': possibly drifted prompt string
              - 'degradation_level': current degradation intensity
              - 'injected': whether degradation was applied
        """
        self._step_count = step_id
        level = self.current_degradation_level
        injected = level > 0.0

        result: Dict[str, Any] = {
            "context": context,
            "system_prompt": system_prompt,
            "degradation_level": level,
            "injected": injected,
        }

        if not injected:
            return result

        if self.strategy == DegradationStrategy.TRUNCATION and context is not None:
            result["context"] = self._apply_truncation(context, level)
        elif self.strategy == DegradationStrategy.NOISE and context is not None:
            result["context"] = self._apply_noise(context, level)
        elif self.strategy == DegradationStrategy.DRIFT and system_prompt is not None:
            result["system_prompt"] = self._apply_drift(system_prompt, level)

        self._injection_count += 1
        self._records.append(InjectionRecord(
            injector_type="context_degradation",
            failure_type=self.strategy.value,
            target=f"step_{step_id}",
            step_id=step_id,
            message=f"Degradation level {level:.2f} at step {step_id}",
        ))

        return result

    def _apply_truncation(
        self, context: List[Dict[str, Any]], level: float
    ) -> List[Dict[str, Any]]:
        """Remove earlier context entries proportional to degradation level.

        At level 0.0, nothing is removed. At level 1.0, up to
        max_truncation_pct of entries are dropped from the front.
        The system prompt (first entry, if present) is always preserved.
        """
        if len(context) <= 1:
            return context

        # Calculate how many entries to drop (from the front, after system prompt)
        drop_pct = level * self.max_truncation_pct
        drop_count = max(1, int(len(context) * drop_pct)) if drop_pct > 0 else 0

        # Never drop the system prompt (index 0 if it has role='system')
        start_idx = 1 if context[0].get("role") == "system" else 0
        drop_count = min(drop_count, len(context) - start_idx - 1)

        if drop_count <= 0:
            return context

        return context[:start_idx] + context[start_idx + drop_count:]

    def _apply_noise(
        self, context: List[Dict[str, Any]], level: float
    ) -> List[Dict[str, Any]]:
        """Inject random character substitutions into context content.

        Noise rate scales with degradation level. At level 0.1, roughly
        1% of characters are perturbed. At level 1.0, up to 10%.
        """
        noisy = []
        noise_rate = level * 0.1  # Max 10% character corruption

        for entry in context:
            if "content" not in entry or not isinstance(entry["content"], str):
                noisy.append(entry)
                continue

            content = entry["content"]
            chars = list(content)
            for i in range(len(chars)):
                if self._rng.random() < noise_rate:
                    # Replace with a random visible ASCII character
                    chars[i] = chr(self._rng.randint(33, 126))

            noisy.append({**entry, "content": "".join(chars)})

        return noisy

    def _apply_drift(self, prompt: str, level: float) -> str:
        """Gradually shift system prompt instructions.

        Drift accumulates over time — each step adds a small random
        perturbation. The drift is deterministic (seeded) and reversible
        for testing. At high levels, critical instructions may be
        replaced with plausible but incorrect alternatives.
        """
        # Accumulate drift — this compounds across steps
        self._drift_accumulator += level * 0.05

        drift_pct = min(0.5, self._drift_accumulator)
        words = prompt.split()

        if not words:
            return prompt

        # Replace a fraction of words with similar-looking alternatives
        word_count = max(1, int(len(words) * drift_pct))
        indices = self._rng.sample(range(len(words)), min(word_count, len(words)))

        for idx in indices:
            word = words[idx]
            if len(word) <= 2:
                continue  # Don't drift short words (prepositions, etc.)
            # Character-level perturbation: swap two adjacent characters
            if len(word) > 3:
                pos = self._rng.randint(1, len(word) - 2)
                word_list = list(word)
                word_list[pos], word_list[pos + 1] = word_list[pos + 1], word_list[pos]
                words[idx] = "".join(word_list)

        return " ".join(words)

    def make_validator(
        self,
        original_context: Optional[List[Dict[str, Any]]] = None,
        original_prompt: Optional[str] = None,
    ) -> Callable[[Any], bool]:
        """Create a validator function for use with assert_no_silent_failure.

        Returns a callable that checks whether the agent's output is
        still valid given the degradation that was applied. This wires
        chaos injection into the silent failure detection pipeline.

        Args:
            original_context: The original (pre-degradation) context.
            original_prompt: The original (pre-degradation) system prompt.

        Returns:
            A validator function that returns True if output is valid.
        """
        degraded_level = self.current_degradation_level

        def _validate(output: Any) -> bool:
            if output is None:
                return False
            # At low degradation, any non-None output is acceptable
            if degraded_level < 0.3:
                return True
            # At moderate degradation, check output is non-empty string
            if isinstance(output, str):
                return len(output.strip()) > 0
            # At high degradation, output must be non-empty
            return bool(output)

        return _validate


# ──────────────────────────────────────────────────────
# CascadingFailures — multi-agent error propagation
# ──────────────────────────────────────────────────────


class CascadingFailures:
    """Simulates error propagation in multi-agent systems.

    When one agent or component fails, related components often fail
    shortly after — a database timeout cascades to API errors, which
    cascade to user-facing failures. This injector models that domino
    effect with configurable probability and depth.

    Args:
        cascade_probability: Probability that each failure triggers
                             an additional failure (0.0-1.0).
        max_cascade_depth: Maximum number of cascading failures from
                           a single root cause (prevents infinite chains).
        propagation_delay_steps: Steps between cascade levels (0 = immediate).
        seed: Random seed for deterministic cascade behavior.
    """

    def __init__(
        self,
        cascade_probability: float = 0.5,
        max_cascade_depth: int = 3,
        propagation_delay_steps: int = 1,
        seed: Optional[int] = None,
    ) -> None:
        self.cascade_probability = max(0.0, min(1.0, cascade_probability))
        self.max_cascade_depth = max_cascade_depth
        self.propagation_delay_steps = propagation_delay_steps
        self._rng = random.Random(seed)

        self._injection_count: int = 0
        self._records: List[InjectionRecord] = []
        # Active cascade chains: root_failure_id -> current depth
        self._active_chains: Dict[str, int] = {}

    @property
    def injection_count(self) -> int:
        return self._injection_count

    @property
    def records(self) -> List[InjectionRecord]:
        return list(self._records)

    def reset(self) -> None:
        self._injection_count = 0
        self._records.clear()
        self._active_chains.clear()

    def on_failure(
        self,
        failure_event: Dict[str, Any],
        current_step: int = 0,
    ) -> List[Dict[str, Any]]:
        """Process a failure event and return any cascading failures.

        Args:
            failure_event: Dict describing the root failure.
                Required keys: 'tool_name' or 'agent_id', 'error_type'
                Optional keys: 'step_id', 'message'
            current_step: Current step number for timing propagation.

        Returns:
            List of cascading failure dicts. Empty if no cascade triggered.
            Each dict has: 'triggered_by', 'tool_name', 'error_type',
            'cascade_depth', 'step_id', 'message'
        """
        # Generate a chain ID from the failure event
        chain_id = self._chain_id(failure_event)

        # Check if this chain already exists and at max depth
        current_depth = self._active_chains.get(chain_id, 0)
        if current_depth >= self.max_cascade_depth:
            return []

        cascades: List[Dict[str, Any]] = []
        # First failure always triggers (depth 0 = root)
        # Subsequent failures depend on cascade_probability
        if current_depth > 0 and self._rng.random() > self.cascade_probability:
            return []

        # Generate cascade failure
        new_depth = current_depth + 1
        self._active_chains[chain_id] = new_depth

        # Propagation delay — schedule cascade for a future step
        target_step = current_step + self.propagation_delay_steps

        cascade_event = {
            "triggered_by": failure_event.get(
                "tool_name", failure_event.get("agent_id", "unknown")
            ),
            "tool_name": self._derive_cascading_target(failure_event),
            "error_type": self._derive_cascading_error(failure_event),
            "cascade_depth": new_depth,
            "step_id": target_step,
            "message": (
                f"Cascade depth {new_depth}: "
                f"{self._derive_cascading_error(failure_event)} "
                f"triggered by {failure_event.get('tool_name', 'unknown')}"
            ),
        }
        cascades.append(cascade_event)

        self._injection_count += 1
        self._records.append(InjectionRecord(
            injector_type="cascading_failure",
            failure_type=cascade_event["error_type"],
            target=cascade_event["tool_name"],
            step_id=target_step,
            message=cascade_event["message"],
        ))

        # Recurse: cascading failures can cascade further
        if new_depth < self.max_cascade_depth:
            further = self.on_failure(cascade_event, current_step=target_step)
            cascades.extend(further)

        return cascades

    def _chain_id(self, event: Dict[str, Any]) -> str:
        """Generate a deterministic chain ID for a failure event."""
        key = f"{event.get('tool_name', '')}:{event.get('error_type', '')}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def _derive_cascading_target(self, event: Dict[str, Any]) -> str:
        """Derive the tool/agent that fails next in the cascade.

        Uses a simple name-based heuristic: downstream dependencies
        often share a prefix or are named in the error context.
        """
        original = event.get("tool_name", event.get("agent_id", "unknown"))
        # Common cascade patterns in multi-agent systems
        cascade_map = {
            "database": "api_server",
            "api_server": "user_interface",
            "search": "indexer",
            "auth": "api_server",
            "cache": "database",
        }
        for pattern, target in cascade_map.items():
            if pattern in original.lower():
                return target
        # Default: same tool fails again (retry storm)
        return original

    def _derive_cascading_error(self, event: Dict[str, Any]) -> str:
        """Derive the error type for the cascading failure.

        Cascading failures often manifest differently from root causes.
        A timeout becomes a connection refused; a 500 becomes a 503.
        """
        error_type = event.get("error_type", "error")
        cascade_errors = {
            "timeout": "connection_refused",
            "error": "service_unavailable",
            "rate_limit": "timeout",
            "connection_refused": "service_unavailable",
            "malformed": "timeout",
        }
        return cascade_errors.get(error_type, "error")

    def get_active_chains(self) -> Dict[str, int]:
        """Get current cascade chain states."""
        return dict(self._active_chains)

    def summary(self) -> Dict[str, Any]:
        """Get a summary of cascade state."""
        return {
            "total_cascades": self._injection_count,
            "active_chains": len(self._active_chains),
            "max_depth_reached": (
                max(self._active_chains.values()) if self._active_chains else 0
            ),
            "chain_details": dict(self._active_chains),
        }

    def make_validator(self) -> Callable[[Any], bool]:
        """Create a validator for assert_no_silent_failure.

        Checks that cascading failures didn't cause the agent to
        produce empty or corrupted output.
        """
        def _validate(output: Any) -> bool:
            if output is None:
                return False
            if isinstance(output, str):
                return len(output.strip()) > 0
            return bool(output)

        return _validate


# ──────────────────────────────────────────────────────
# SpecDrift — agent improvisation under pressure
# ──────────────────────────────────────────────────────


class SpecDrift:
    """Simulates agent improvisation when operating under pressure.

    When agents face timeouts, resource constraints, or cascading
    failures, they sometimes improvise — deviating from the original
    specification to "make it work." This injector models that
    behavioral drift with configurable intensity and probability.

    Drift events represent moments where the agent might:
      - Skip a validation step
      - Use a fallback value instead of computing
      - Reorder steps for efficiency
      - Substitute a different tool than specified

    Args:
        intensity: Drift intensity level (see DriftIntensity).
        start_step: Step at which drift injection begins.
        probability: Base probability of drift per step (0.0-1.0).
        seed: Random seed for deterministic drift.
        trigger_events: List of error types that increase drift probability.
                        Default: ["timeout", "rate_limit", "error"]
    """

    def __init__(
        self,
        intensity: str = "subtle",
        start_step: int = 5,
        probability: float = 0.1,
        seed: Optional[int] = None,
        trigger_events: Optional[List[str]] = None,
    ) -> None:
        self.intensity = DriftIntensity(intensity)
        self.start_step = start_step
        self.probability = max(0.0, min(1.0, probability))
        self._rng = random.Random(seed)
        self.trigger_events = trigger_events or ["timeout", "rate_limit", "error"]

        self._step_count: int = 0
        self._injection_count: int = 0
        self._records: List[InjectionRecord] = []
        # Cumulative drift score — increases with each injection
        self._cumulative_drift: float = 0.0
        # History of drift events for assertion
        self._drift_events: List[Dict[str, Any]] = []

    @property
    def injection_count(self) -> int:
        return self._injection_count

    @property
    def records(self) -> List[InjectionRecord]:
        return list(self._records)

    @property
    def cumulative_drift(self) -> float:
        """Cumulative drift score (0.0 = no drift, 1.0 = fully diverged)."""
        return min(1.0, self._cumulative_drift)

    @property
    def drift_events(self) -> List[Dict[str, Any]]:
        """History of all drift injection events."""
        return list(self._drift_events)

    def reset(self) -> None:
        self._step_count = 0
        self._injection_count = 0
        self._records.clear()
        self._cumulative_drift = 0.0
        self._drift_events.clear()

    def check_step(
        self,
        step_id: int,
        recent_errors: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Check whether drift should be injected at this step.

        Args:
            step_id: Current step number.
            recent_errors: List of recent error types (amplifies drift).

        Returns:
            Drift event dict if injection should occur, None otherwise.
            Dict has keys: 'step_id', 'drift_type', 'drift_magnitude',
            'description', 'cumulative_drift'
        """
        self._step_count = step_id

        if step_id < self.start_step:
            return None

        # Calculate effective probability — errors amplify drift
        effective_prob = self.probability
        if recent_errors:
            trigger_count = sum(
                1 for e in recent_errors if e in self.trigger_events
            )
            # Each trigger event adds 20% to the base probability
            effective_prob = min(1.0, effective_prob + trigger_count * 0.2)

        # Intensity multiplier
        intensity_mult = {
            DriftIntensity.SUBTLE: 0.5,
            DriftIntensity.MODERATE: 1.0,
            DriftIntensity.AGGRESSIVE: 2.0,
        }[self.intensity]

        effective_prob *= intensity_mult

        if self._rng.random() >= effective_prob:
            return None

        # Generate drift event
        drift_type = self._rng.choice([
            "skip_validation",
            "use_fallback",
            "reorder_steps",
            "substitute_tool",
            "truncate_output",
            "approximate_result",
        ])

        # Magnitude depends on intensity
        magnitude_base = {
            DriftIntensity.SUBTLE: 0.1,
            DriftIntensity.MODERATE: 0.3,
            DriftIntensity.AGGRESSIVE: 0.6,
        }[self.intensity]
        magnitude = min(1.0, magnitude_base * (1.0 + self._rng.random()))

        self._cumulative_drift += magnitude * 0.1
        self._injection_count += 1

        event = {
            "step_id": step_id,
            "drift_type": drift_type,
            "drift_magnitude": round(magnitude, 3),
            "description": self._drift_description(drift_type, magnitude),
            "cumulative_drift": round(self.cumulative_drift, 3),
        }
        self._drift_events.append(event)

        self._records.append(InjectionRecord(
            injector_type="spec_drift",
            failure_type=drift_type,
            target=f"step_{step_id}",
            step_id=step_id,
            message=event["description"],
        ))

        return event

    def _drift_description(self, drift_type: str, magnitude: float) -> str:
        """Generate a human-readable description of the drift event."""
        descriptions = {
            "skip_validation": (
                f"Agent skipped input validation (magnitude {magnitude:.2f})"
            ),
            "use_fallback": (
                f"Agent used fallback value instead of computing (magnitude {magnitude:.2f})"
            ),
            "reorder_steps": (
                f"Agent reordered execution steps (magnitude {magnitude:.2f})"
            ),
            "substitute_tool": (
                f"Agent substituted different tool than specified (magnitude {magnitude:.2f})"
            ),
            "truncate_output": (
                f"Agent truncated output to save tokens (magnitude {magnitude:.2f})"
            ),
            "approximate_result": (
                f"Agent approximated result instead of precise computation (magnitude {magnitude:.2f})"
            ),
        }
        return descriptions.get(drift_type, f"Unknown drift (magnitude {magnitude:.2f})")

    def get_drift_score(self) -> Dict[str, Any]:
        """Get a comprehensive drift assessment."""
        return {
            "cumulative_drift": self.cumulative_drift,
            "total_events": self._injection_count,
            "drift_types": {
                dt: sum(1 for e in self._drift_events if e["drift_type"] == dt)
                for dt in set(e["drift_type"] for e in self._drift_events)
            } if self._drift_events else {},
            "max_magnitude": (
                max(e["drift_magnitude"] for e in self._drift_events)
                if self._drift_events else 0.0
            ),
            "intensity": self.intensity.value,
        }

    def make_validator(self) -> Callable[[Any], bool]:
        """Create a validator for assert_no_silent_failure.

        Checks that spec drift didn't cause the agent to produce
        empty or invalid output. The validator adapts its strictness
        based on cumulative drift — higher drift means stricter checks.
        """
        drift_level = self.cumulative_drift

        def _validate(output: Any) -> bool:
            if output is None:
                return False
            # Low drift: any non-None output is acceptable
            if drift_level < 0.3:
                return True
            # Moderate drift: check output is meaningful
            if isinstance(output, str):
                return len(output.strip()) > 10  # Non-trivial content
            return bool(output)

        return _validate


# ──────────────────────────────────────────────────────
# ChaosBudget — failure budget management
# ──────────────────────────────────────────────────────


class ChaosBudget:
    """Manages a budget of failures for a test run.

    Tracks total failures across all injectors and enforces a hard cap.
    Once the budget is exhausted, no more failures are injected regardless
    of individual injector configuration.

    Supports fluent API for composing multiple injectors:

        chaos = (ChaosBudget(max_failures=3)
            .add(ToolFailureInjector(tool_name="search", failure_type="timeout"))
            .add(LLMFailureInjector(failure_type="rate_limit")))

    Args:
        max_failures: Maximum total failures allowed in this test run.
                      Set to 0 for unlimited.
    """

    def __init__(self, max_failures: int = 5) -> None:
        self.max_failures = max_failures
        self._injectors: List[FailureInjector] = []
        self._total_injected: int = 0

    @property
    def total_injected(self) -> int:
        """Total failures injected across all injectors."""
        return sum(inj.injection_count for inj in self._injectors)

    @property
    def remaining(self) -> int:
        """Remaining failures in the budget."""
        if self.max_failures == 0:
            return -1  # Unlimited
        return max(0, self.max_failures - self.total_injected)

    @property
    def exhausted(self) -> bool:
        """Whether the failure budget is exhausted."""
        if self.max_failures == 0:
            return False  # Unlimited
        return self.total_injected >= self.max_failures

    @property
    def records(self) -> List[InjectionRecord]:
        """All injection records across all injectors."""
        all_records = []
        for inj in self._injectors:
            all_records.extend(inj.records)
        return sorted(all_records, key=lambda r: r.timestamp)

    @property
    def records_by_type(self) -> Dict[str, List[InjectionRecord]]:
        """Injection records grouped by injector type."""
        result: Dict[str, List[InjectionRecord]] = {}
        for record in self.records:
            result.setdefault(record.injector_type, []).append(record)
        return result

    @property
    def records_by_failure(self) -> Dict[str, List[InjectionRecord]]:
        """Injection records grouped by failure type."""
        result: Dict[str, List[InjectionRecord]] = {}
        for record in self.records:
            result.setdefault(record.failure_type, []).append(record)
        return result

    def add(self, injector: FailureInjector) -> ChaosBudget:
        """Add a failure injector to the budget.

        Returns self for fluent chaining.
        """
        self._injectors.append(injector)
        return self

    def get_injectors(self) -> List[FailureInjector]:
        """Get all registered injectors."""
        return list(self._injectors)

    def can_inject(self) -> bool:
        """Check whether more failures can be injected."""
        if self.max_failures == 0:
            return True
        return self.total_injected < self.max_failures

    def check_budget(self) -> None:
        """Raise if the failure budget is exhausted.

        Raises:
            ChaosBudgetExhausted: When the budget has no remaining failures.
        """
        if not self.can_inject():
            raise ChaosBudgetExhausted(
                f"Chaos budget exhausted: {self.total_injected}/{self.max_failures} "
                f"failures used. No more injections allowed."
            )

    def reset(self) -> None:
        """Reset all injectors and clear injection history."""
        for inj in self._injectors:
            inj.reset()
        self._total_injected = 0

    def summary(self) -> Dict[str, Any]:
        """Get a summary of the chaos budget state."""
        return {
            "max_failures": self.max_failures,
            "total_injected": self.total_injected,
            "remaining": self.remaining,
            "exhausted": self.exhausted,
            "injector_count": len(self._injectors),
            "injector_details": [
                {
                    "type": type(inj).__name__,
                    "injection_count": inj.injection_count,
                }
                for inj in self._injectors
            ],
        }


class ChaosBudgetExhausted(Exception):
    """Raised when the chaos failure budget is exhausted."""
    pass
