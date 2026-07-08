"""Generic hook-based adapter for Sentinel.

Framework-agnostic adapter that intercepts any callable tool function and
records calls into AgentTrace. Works with custom agents, proprietary frameworks,
or any agent that uses plain function calls as tools.

Unlike the LangChain/CrewAI/OpenAI adapters which are tied to specific
framework APIs, this adapter uses a simple hook-based pattern:
- Before-hook: called before the tool executes (can modify args)
- After-hook: called after the tool executes (can modify result)
- Error-hook: called when the tool raises an exception

Dependencies: None (pure Python, no framework required).

Usage:
    from sentinel.adapters.generic import HookAdapter, wrap_callable
    from sentinel.env import MockTool
    from sentinel.models import AgentTrace

    # Wrap a simple function
    trace = AgentTrace()
    mock = MockTool("search", response={"results": []})

    @wrap_callable(mock=mock, trace=trace)
    def search(**kwargs):
        return real_search_impl(**kwargs)

    # Or use the adapter directly
    adapter = HookAdapter(
        mock=mock,
        trace=trace,
        name="search",
    )
    result = adapter.execute(query="refund policy")

    # Add hooks for pre/post processing
    adapter.add_before_hook(lambda kwargs: {**kwargs, "limit": 10})
    adapter.add_after_hook(lambda result, kwargs: result[:5])
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Dict, List, Optional

from sentinel.env import MockTool
from sentinel.models import AgentTrace, ToolCall


# Type aliases for hook callables
BeforeHook = Callable[[Dict[str, Any]], Dict[str, Any]]
AfterHook = Callable[[Any, Dict[str, Any]], Any]
ErrorHook = Callable[[Exception, Dict[str, Any]], None]


# ──────────────────────────────────────────────────────
# HookAdapter — generic callable wrapper with hooks
# ──────────────────────────────────────────────────────


class HookAdapter:
    """Generic adapter that wraps any callable with sentinel tracing.

    Provides a framework-agnostic way to intercept tool calls, record them
    into an AgentTrace, and optionally apply before/after/error hooks.

    The adapter delegates to a MockTool for response generation (like the
    framework-specific adapters) but also supports executing the original
    function when no mock is provided.

    Hook chains execute in registration order:
    - Before hooks: transform kwargs before execution
    - After hooks: transform result after execution
    - Error hooks: notified on exception (do not modify the exception)

    Args:
        mock: The sentinel MockTool for canned responses. If None, the
              original function is called instead.
        trace: AgentTrace to record all tool calls into.
        name: Tool name for identification in traces.
        description: Tool description (for documentation).
        fn: Optional original function to wrap. When mock is None,
            this function is called directly.
    """

    def __init__(
        self,
        trace: AgentTrace,
        mock: Optional[MockTool] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        fn: Optional[Callable[..., Any]] = None,
    ) -> None:
        if mock is None and fn is None:
            raise ValueError("Either mock or fn must be provided")

        self._mock = mock
        self._trace = trace
        self._fn = fn
        self.name: str = name or (mock.name if mock else (fn.__name__ if fn else "unknown"))
        self.description: str = description or (
            f"Sentinel mock tool: {self.name}" if mock
            else f"Sentinel wrapped function: {self.name}"
        )

        # Hook chains — registered in order, executed in order
        self._before_hooks: List[BeforeHook] = []
        self._after_hooks: List[AfterHook] = []
        self._error_hooks: List[ErrorHook] = []

    @property
    def mock(self) -> Optional[MockTool]:
        """Access the underlying sentinel MockTool (if any)."""
        return self._mock

    @property
    def trace(self) -> AgentTrace:
        """Access the AgentTrace this adapter records into."""
        return self._trace

    # ──────────────────────────────────────────────────────
    # Hook registration
    # ──────────────────────────────────────────────────────

    def add_before_hook(self, hook: BeforeHook) -> None:
        """Register a before-hook.

        The hook receives the kwargs dict and returns a (possibly modified)
        kwargs dict. Multiple before-hooks chain: each receives the output
        of the previous one.

        Args:
            hook: Callable that takes Dict[str, Any] and returns Dict[str, Any].
        """
        self._before_hooks.append(hook)

    def add_after_hook(self, hook: AfterHook) -> None:
        """Register an after-hook.

        The hook receives (result, kwargs) and returns a (possibly modified)
        result. Multiple after-hooks chain: each receives the output of
        the previous one.

        Args:
            hook: Callable that takes (Any, Dict[str, Any]) and returns Any.
        """
        self._after_hooks.append(hook)

    def add_error_hook(self, hook: ErrorHook) -> None:
        """Register an error-hook.

        The hook receives (exception, kwargs) and is called for side effects
        only (logging, metrics, etc.). It does NOT modify the exception.

        Args:
            hook: Callable that takes (Exception, Dict[str, Any]) and returns None.
        """
        self._error_hooks.append(hook)

    def clear_hooks(self) -> None:
        """Remove all registered hooks."""
        self._before_hooks.clear()
        self._after_hooks.clear()
        self._error_hooks.clear()

    # ──────────────────────────────────────────────────────
    # Execution
    # ──────────────────────────────────────────────────────

    def execute(self, **kwargs: Any) -> Any:
        """Execute the tool with hook processing and trace recording.

        Flow:
            1. Apply before-hooks to kwargs
            2. Call mock tool (or original function)
            3. Apply after-hooks to result
            4. Record everything into the trace

        Returns the (possibly hook-transformed) result.

        Raises the original exception after calling error-hooks.
        """
        # Apply before-hooks
        processed_kwargs = dict(kwargs)
        for hook in self._before_hooks:
            processed_kwargs = hook(processed_kwargs)

        start = time.time()
        result = None
        error_msg = None

        try:
            if self._mock is not None:
                result = self._mock(**processed_kwargs)
            elif self._fn is not None:
                result = self._fn(**processed_kwargs)
            else:
                raise RuntimeError("No mock or function configured")
        except Exception as exc:
            error_msg = str(exc)
            # Notify error hooks (side-effect only)
            for hook in self._error_hooks:
                try:
                    hook(exc, processed_kwargs)
                except Exception:
                    pass  # Don't let error hooks mask the original error
            raise
        finally:
            # Apply after-hooks (only if no error)
            if error_msg is None:
                for hook in self._after_hooks:
                    try:
                        result = hook(result, processed_kwargs)
                    except Exception:
                        pass  # Don't let after-hooks mask the original result

            duration_ms = (time.time() - start) * 1000
            tool_call = ToolCall(
                tool_name=self.name,
                arguments=processed_kwargs,
                result=result,
                duration_ms=duration_ms,
                error=error_msg,
            )
            self._trace.add_tool_call(tool_call)

        return result

    def __call__(self, **kwargs: Any) -> Any:
        """Direct call interface — delegates to execute."""
        return self.execute(**kwargs)

    def reset_calls(self) -> None:
        """Clear recorded calls on the mock tool (if any)."""
        if self._mock is not None:
            self._mock.calls.clear()

    def __repr__(self) -> str:
        source = "mock" if self._mock else "fn"
        return (
            f"HookAdapter(name={self.name!r}, source={source}, "
            f"before_hooks={len(self._before_hooks)}, "
            f"after_hooks={len(self._after_hooks)}, "
            f"error_hooks={len(self._error_hooks)})"
        )


# ──────────────────────────────────────────────────────
# wrap_callable — decorator for wrapping functions
# ──────────────────────────────────────────────────────


def wrap_callable(
    mock: MockTool,
    trace: AgentTrace,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Callable[[Callable[..., Any]], HookAdapter]:
    """Decorator that wraps a function with a sentinel HookAdapter.

    The decorated function is replaced by a HookAdapter instance that
    records calls into the trace. The original function is still accessible
    via ``adapter._fn``.

    Args:
        mock: The sentinel MockTool for canned responses.
        trace: AgentTrace to record all tool calls into.
        name: Tool name (defaults to the function name).
        description: Tool description (defaults to the function docstring).

    Example:
        @wrap_callable(mock=search_mock, trace=trace)
        def search(**kwargs):
            return real_search(**kwargs)

        # search is now a HookAdapter — call it like a function
        result = search(query="test")
    """

    def decorator(fn: Callable[..., Any]) -> HookAdapter:
        adapter = HookAdapter(
            mock=mock,
            trace=trace,
            name=name or fn.__name__,
            description=description or fn.__doc__ or f"Wrapped: {fn.__name__}",
            fn=fn,
        )
        # Preserve the original function for inspection
        adapter._original_fn = fn  # type: ignore[attr-defined]
        return adapter

    return decorator


# ──────────────────────────────────────────────────────
# HookAdapterGroup — manage multiple adapters as a unit
# ──────────────────────────────────────────────────────


class HookAdapterGroup:
    """Manages a collection of HookAdapters as a logical unit.

    Useful for wrapping multiple tools at once and providing a unified
    interface for hook registration and trace access.

    Args:
        trace: Shared AgentTrace for all adapters in the group.
    """

    def __init__(self, trace: AgentTrace) -> None:
        self._trace = trace
        self._adapters: Dict[str, HookAdapter] = {}

    def add(
        self,
        mock: MockTool,
        name: Optional[str] = None,
        description: Optional[str] = None,
        fn: Optional[Callable[..., Any]] = None,
    ) -> HookAdapter:
        """Add a tool to the group.

        Args:
            mock: MockTool for canned responses.
            name: Tool name (defaults to mock.name).
            description: Tool description.
            fn: Optional original function.

        Returns:
            The created HookAdapter (for further configuration).
        """
        tool_name = name or mock.name
        adapter = HookAdapter(
            mock=mock,
            trace=self._trace,
            name=tool_name,
            description=description,
            fn=fn,
        )
        self._adapters[tool_name] = adapter
        return adapter

    def get(self, name: str) -> Optional[HookAdapter]:
        """Get an adapter by name."""
        return self._adapters.get(name)

    @property
    def adapters(self) -> Dict[str, HookAdapter]:
        """All adapters in the group."""
        return dict(self._adapters)

    @property
    def trace(self) -> AgentTrace:
        """Shared AgentTrace."""
        return self._trace

    def apply_before_hook_to_all(self, hook: BeforeHook) -> None:
        """Register a before-hook on every adapter in the group."""
        for adapter in self._adapters.values():
            adapter.add_before_hook(hook)

    def apply_after_hook_to_all(self, hook: AfterHook) -> None:
        """Register an after-hook on every adapter in the group."""
        for adapter in self._adapters.values():
            adapter.add_after_hook(hook)

    def apply_error_hook_to_all(self, hook: ErrorHook) -> None:
        """Register an error-hook on every adapter in the group."""
        for adapter in self._adapters.values():
            adapter.add_error_hook(hook)

    def clear_all_hooks(self) -> None:
        """Clear all hooks on every adapter."""
        for adapter in self._adapters.values():
            adapter.clear_hooks()

    def __repr__(self) -> str:
        return (
            f"HookAdapterGroup(tools={list(self._adapters.keys())}, "
            f"trace_calls={self._trace.total_tool_calls})"
        )
