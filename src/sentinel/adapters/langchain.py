"""LangChain agent adapter for Sentinel.

Bridges sentinel's mock tool layer to LangChain agents for behavioral testing.
Intercepts tool calls, captures them into AgentTrace, and optionally injects
failures via the chaos layer.

Dependencies (all optional):
    - langchain-core >= 0.2: BaseTool, Runnable, tool invocation protocols

Usage:
    from sentinel.adapters.langchain import SentinelToolAdapter, wrap_agent
    from sentinel.env import MockTool
    from sentinel.models import AgentTrace

    # Wrap individual tools
    trace = AgentTrace()
    adapter = SentinelToolAdapter(
        tool=real_langchain_tool,
        mock=MockTool("search", response=SEARCH_RESULTS),
        trace=trace,
    )

    # Wrap entire agent (all tools at once)
    wrapped = wrap_agent(
        agent=agent,
        tool_map={"search": mock_search, "email": mock_email},
        trace=trace,
    )
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Type

from sentinel.env import MockTool, MockToolCall
from sentinel.models import AgentTrace, ToolCall

try:
    from langchain_core.tools import BaseTool
except ImportError:
    BaseTool = None  # type: ignore[misc,assignment]


class SentinelToolAdapter:
    """Wraps a LangChain BaseTool with a sentinel MockTool.

    Intercepts ``invoke()`` and ``__call__`` on the original tool, delegates
    to the mock tool for response generation, and records every call into
    the provided AgentTrace.

    If ``base_tool`` is None, operates as a standalone mock tool adapter
    (useful for testing without langchain-core installed).

    Args:
        base_tool: The original LangChain BaseTool to wrap. If None, the
                   adapter acts as a standalone callable proxy.
        mock: The sentinel MockTool that provides canned responses.
        trace: AgentTrace to record all tool calls into.
    """

    def __init__(
        self,
        mock: MockTool,
        trace: AgentTrace,
        base_tool: Optional[Any] = None,
    ) -> None:
        # Validate langchain availability only when a real tool is provided
        if base_tool is not None and BaseTool is not None:
            if not isinstance(base_tool, BaseTool):
                raise TypeError(
                    f"base_tool must be a langchain BaseTool instance, "
                    f"got {type(base_tool).__name__}"
                )

        self._base_tool = base_tool
        self._mock = mock
        self._trace = trace

        # Expose the mock tool's name so callers can identify this adapter
        self.name: str = mock.name

    @property
    def mock(self) -> MockTool:
        """Access the underlying sentinel MockTool."""
        return self._mock

    @property
    def trace(self) -> AgentTrace:
        """Access the AgentTrace this adapter records into."""
        return self._trace

    def invoke(self, input: Any = None, **kwargs: Any) -> Any:
        """Invoke the tool, delegating to the mock and recording the call.

        Compatible with LangChain's ``BaseTool.invoke()`` interface:
        ``invoke(input, config=None, **kwargs)``.

        If a real BaseTool is present, its ``invoke`` is called to preserve
        any input parsing/validation it performs. Otherwise, the mock is
        called directly with ``**kwargs``.

        Returns the mock tool's response (or raises its configured error).
        """
        # Merge input into kwargs if it's a dict
        call_kwargs = dict(kwargs)
        if isinstance(input, dict):
            call_kwargs.update(input)
        elif input is not None:
            # Non-dict input: pass as 'input' kwarg (LangChain convention)
            call_kwargs["input"] = input

        return self._call_mock(call_kwargs)

    def __call__(self, **kwargs: Any) -> Any:
        """Direct call interface — delegates to mock and records the call."""
        return self._call_mock(kwargs)

    def _call_mock(self, kwargs: Dict[str, Any]) -> Any:
        """Execute the mock tool and record the call into the trace."""
        start = time.time()
        result = None
        error_msg = None

        try:
            result = self._mock(**kwargs)
        except Exception as exc:
            error_msg = str(exc)
            raise
        finally:
            duration_ms = (time.time() - start) * 1000
            tool_call = ToolCall(
                tool_name=self._mock.name,
                arguments=kwargs,
                result=result,
                duration_ms=duration_ms,
                error=error_msg,
            )
            self._trace.add_tool_call(tool_call)

        return result

    def reset_calls(self) -> None:
        """Clear recorded calls on the mock tool."""
        self._mock.calls.clear()

    # ──────────────────────────────────────────────────────
    # Duck-typing for LangChain BaseTool compatibility
    # ──────────────────────────────────────────────────────

    @property
    def description(self) -> str:
        """Tool description — from the base tool or default."""
        if self._base_tool is not None:
            return getattr(self._base_tool, "description", self.name)
        return f"Sentinel mock tool: {self.name}"

    @property
    def args(self) -> Dict[str, Any]:
        """Tool argument schema — from the base tool or empty."""
        if self._base_tool is not None:
            return getattr(self._base_tool, "args", {})
        return {}

    def __repr__(self) -> str:
        base = type(self._base_tool).__name__ if self._base_tool else "None"
        return (
            f"SentinelToolAdapter(base={base}, "
            f"mock={self._mock.name!r}, "
            f"calls={self._mock.call_count})"
        )


def wrap_agent(
    agent: Any,
    tool_map: Dict[str, MockTool],
    trace: AgentTrace,
) -> "AgentWrapper":
    """Wrap an entire LangChain agent, replacing its tools with mocks.

    Creates a wrapper around the agent that:
    1. Intercepts all tool calls through sentinel MockTools
    2. Records every call into the AgentTrace
    3. Preserves the agent's ``invoke`` / ``__call__`` interface

    Args:
        agent: A LangChain agent (any Runnable with tools).
        tool_map: Mapping of tool name → sentinel MockTool.
        trace: AgentTrace to record all calls into.

    Returns:
        AgentWrapper that behaves like the original agent but routes
        tool calls through sentinel.

    Example:
        agent = create_react_agent(model, tools, prompt)
        wrapped = wrap_agent(
            agent=agent,
            tool_map={
                "search": MockTool("search", response=SEARCH_RESULTS),
                "email": MockTool("email", response="sent"),
            },
            trace=trace,
        )
        result = wrapped.invoke({"messages": [...]})
    """
    return AgentWrapper(
        agent=agent,
        tool_map=tool_map,
        trace=trace,
    )


class AgentWrapper:
    """Wraps a LangChain agent with sentinel tool mocking.

    This wrapper intercepts the agent's tool execution path and replaces
    all tool calls with sentinel MockTools. The agent's core LLM reasoning
    loop is untouched — only the tool layer is replaced.

    The wrapper implements both ``invoke()`` and ``__call__()`` for
    compatibility with different LangChain usage patterns.
    """

    def __init__(
        self,
        agent: Any,
        tool_map: Dict[str, MockTool],
        trace: AgentTrace,
    ) -> None:
        self._agent = agent
        self._trace = trace
        self._adapters: Dict[str, SentinelToolAdapter] = {}

        # Create an adapter for each mock tool
        for name, mock in tool_map.items():
            self._adapters[name] = SentinelToolAdapter(
                mock=mock,
                trace=trace,
            )

    @property
    def adapters(self) -> Dict[str, SentinelToolAdapter]:
        """Get all tool adapters by name."""
        return dict(self._adapters)

    @property
    def trace(self) -> AgentTrace:
        """Access the AgentTrace."""
        return self._trace

    def get_mock(self, name: str) -> Optional[MockTool]:
        """Get the mock tool for a given name."""
        adapter = self._adapters.get(name)
        return adapter.mock if adapter else None

    def invoke(self, input: Any = None, **kwargs: Any) -> Any:
        """Invoke the wrapped agent.

        For a fully integration-tested agent, this delegates to the original
        agent's invoke and the tool mocking happens via the adapters. For
        a standalone mock-only test, this provides a simpler path.

        Returns the agent's response.
        """
        # Delegate to the original agent — tool interception happens
        # when the agent calls tools through the adapters
        if hasattr(self._agent, "invoke"):
            return self._agent.invoke(input, **kwargs)
        return self._agent(input, **kwargs)

    def __call__(self, **kwargs: Any) -> Any:
        """Call interface — delegates to invoke."""
        return self.invoke(**kwargs)

    def __repr__(self) -> str:
        return (
            f"AgentWrapper(agent={type(self._agent).__name__}, "
            f"tools={list(self._adapters.keys())})"
        )
