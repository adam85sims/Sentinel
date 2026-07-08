"""OpenAI Agents SDK adapter for Sentinel.

Bridges sentinel's mock tool layer to OpenAI Agents SDK for behavioral testing.
Intercepts function tool calls, captures them into AgentTrace, and optionally
injects failures via the chaos layer.

The OpenAI Agents SDK uses ``@function_tool`` to wrap Python functions as tools,
and ``FunctionTool`` for custom tool definitions. This adapter provides both
patterns: a standalone callable that records calls, and a function_tool-compatible
wrapper.

Dependencies (all optional):
    - openai-agents >= 0.1: FunctionTool, function_tool, RunContextWrapper

Usage:
    from sentinel.adapters.openai import SentinelFunctionTool, wrap_openai_agent
    from sentinel.env import MockTool
    from sentinel.models import AgentTrace

    # Create a function tool from a mock
    trace = AgentTrace()
    tool = SentinelFunctionTool(
        mock=MockTool("search", response=SEARCH_RESULTS),
        trace=trace,
        name="search",
        description="Search the knowledge base",
    )

    # Use as a callable (same as OpenAI function_tool pattern)
    result = tool.invoke({"query": "refund policy"})

    # Wrap entire agent
    wrapped = wrap_openai_agent(
        agent=my_agent,
        tool_map={"search": mock_search, "email": mock_email},
        trace=trace,
    )
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional

from sentinel.env import MockTool
from sentinel.models import AgentTrace, ToolCall


# ──────────────────────────────────────────────────────
# SentinelFunctionTool — wraps MockTool as an OpenAI function tool
# ──────────────────────────────────────────────────────


class SentinelFunctionTool:
    """Wraps a sentinel MockTool as an OpenAI Agents SDK function tool.

    Provides ``invoke(args_json)`` which matches the OpenAI SDK's
    ``on_invoke_tool(ctx, args)`` protocol. The tool delegates to the
    mock for response generation and records every call into the
    provided AgentTrace.

    This class duck-types the FunctionTool interface so it works without
    requiring the openai-agents package. When the SDK IS installed, this
    tool can be passed directly to an Agent's ``tools`` list.

    The ``params_json_schema`` property provides a minimal JSON schema
    that lets the SDK (or any caller) introspect the tool's expected
    arguments.

    Args:
        mock: The sentinel MockTool that provides canned responses.
        trace: AgentTrace to record all tool calls into.
        name: Tool name (used by the SDK for identification).
        description: Tool description (shown to the LLM).
        params_json_schema: Optional custom JSON schema for arguments.
                           If None, a generic object schema is generated.
    """

    def __init__(
        self,
        mock: MockTool,
        trace: AgentTrace,
        name: Optional[str] = None,
        description: Optional[str] = None,
        params_json_schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._mock = mock
        self._trace = trace
        self.name: str = name or mock.name
        self.description: str = description or f"Sentinel mock tool: {self.name}"
        self._params_schema = params_json_schema or {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }

    @property
    def mock(self) -> MockTool:
        """Access the underlying sentinel MockTool."""
        return self._mock

    @property
    def trace(self) -> AgentTrace:
        """Access the AgentTrace this adapter records into."""
        return self._trace

    @property
    def params_json_schema(self) -> Dict[str, Any]:
        """JSON schema for the tool's input parameters.

        Matches the OpenAI SDK's FunctionTool.params_json_schema interface.
        """
        return self._params_schema

    def invoke(self, args: Any = None) -> Any:
        """Execute the tool with the given arguments.

        Accepts either a JSON string (OpenAI SDK convention) or a dict.
        Delegates to the mock tool and records the call into the trace.

        Args:
            args: Arguments as a JSON string or dict. If a string, it is
                  parsed as JSON. If None, an empty dict is used.

        Returns the mock tool's response (or raises its configured error).
        """
        # Parse arguments
        if isinstance(args, str):
            try:
                kwargs = json.loads(args)
            except json.JSONDecodeError:
                kwargs = {"input": args}
        elif isinstance(args, dict):
            kwargs = args
        elif args is None:
            kwargs = {}
        else:
            kwargs = {"input": args}

        return self._call_mock(kwargs)

    async def async_invoke(self, args: Any = None) -> Any:
        """Async version of invoke — delegates to the sync path.

        The mock tool is synchronous, so this is a thin wrapper for
        API compatibility with async runners.
        """
        return self.invoke(args)

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
                tool_name=self.name,
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

    def __call__(self, **kwargs: Any) -> Any:
        """Direct call interface — delegates to mock and records the call."""
        return self._call_mock(kwargs)

    def __repr__(self) -> str:
        return (
            f"SentinelFunctionTool(name={self.name!r}, "
            f"calls={self._mock.call_count})"
        )


# ──────────────────────────────────────────────────────
# OpenAIAgentWrapper — wraps an OpenAI Agent with sentinel mocking
# ──────────────────────────────────────────────────────


class OpenAIAgentWrapper:
    """Wraps an OpenAI Agents SDK Agent with sentinel tool mocking.

    Intercepts the agent's tool execution path and replaces all function
    tools with sentinel MockTools. The agent's core LLM reasoning loop is
    untouched — only the tool layer is replaced.

    Note:
        For full integration testing, wire the adapter tools into the
        agent's ``tools`` list before running via ``Runner.run()``.
        This wrapper handles the bookkeeping of adapters and trace.
    """

    def __init__(
        self,
        agent: Any,
        tool_map: Dict[str, MockTool],
        trace: AgentTrace,
    ) -> None:
        self._agent = agent
        self._trace = trace
        self._adapters: Dict[str, SentinelFunctionTool] = {}

        # Create an adapter for each mock tool
        for tool_name, mock in tool_map.items():
            self._adapters[tool_name] = SentinelFunctionTool(
                mock=mock,
                trace=trace,
                name=tool_name,
            )

    @property
    def adapters(self) -> Dict[str, SentinelFunctionTool]:
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

    def get_adapter(self, name: str) -> Optional[SentinelFunctionTool]:
        """Get the adapter tool for a given name."""
        return self._adapters.get(name)

    def get_tool_list(self) -> List[SentinelFunctionTool]:
        """Get all adapters as a list (for passing to Agent.tools)."""
        return list(self._adapters.values())

    def __repr__(self) -> str:
        return (
            f"OpenAIAgentWrapper(agent={type(self._agent).__name__}, "
            f"tools={list(self._adapters.keys())})"
        )


def wrap_openai_agent(
    agent: Any,
    tool_map: Dict[str, MockTool],
    trace: AgentTrace,
) -> OpenAIAgentWrapper:
    """Wrap an OpenAI Agents SDK Agent with sentinel tool mocking.

    Creates a wrapper around the agent that:
    1. Creates SentinelFunctionTool adapters for each mock tool
    2. Records every call into the AgentTrace
    3. Provides get_tool_list() for easy wiring into the agent's tools

    Args:
        agent: An OpenAI Agents SDK Agent instance.
        tool_map: Mapping of tool name → sentinel MockTool.
        trace: AgentTrace to record all calls into.

    Returns:
        OpenAIAgentWrapper with adapters ready for wiring.

    Example:
        from sentinel.adapters.openai import wrap_openai_agent
        from sentinel.env import MockTool

        wrapper = wrap_openai_agent(
            agent=my_agent,
            tool_map={
                "search": MockTool("search", response=SEARCH_RESULTS),
                "email": MockTool("email", response="sent"),
            },
            trace=trace,
        )
        # Wire into agent:
        my_agent.tools = wrapper.get_tool_list()
    """
    return OpenAIAgentWrapper(
        agent=agent,
        tool_map=tool_map,
        trace=trace,
    )
