"""CrewAI agent adapter for Sentinel.

Bridges sentinel's mock tool layer to CrewAI agents for behavioral testing.
Intercepts tool calls via CrewAI's BaseTool._run() protocol, captures them
into AgentTrace, and optionally injects failures via the chaos layer.

Dependencies (all optional):
    - crewai >= 0.80: BaseTool, @tool decorator

Usage:
    from sentinel.adapters.crewai import SentinelCrewTool, wrap_crew_agent
    from sentinel.env import MockTool
    from sentinel.models import AgentTrace

    # Wrap individual tools
    trace = AgentTrace()
    adapter = SentinelCrewTool(
        mock=MockTool("search", response=SEARCH_RESULTS),
        trace=trace,
        name="search",
        description="Search the knowledge base",
    )

    # Use as a CrewAI BaseTool — agent calls adapter.run(**kwargs)
    result = adapter.run(query="refund policy")

    # Wrap entire crew (all agents' tools at once)
    wrapped = wrap_crew_agent(
        crew=my_crew,
        tool_map={"search": mock_search, "email": mock_email},
        trace=trace,
    )
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Type

from sentinel.env import MockTool
from sentinel.models import AgentTrace, ToolCall

try:
    from crewai.tools import BaseTool as CrewBaseTool
except ImportError:
    CrewBaseTool = None  # type: ignore[misc,assignment]

try:
    from pydantic import BaseModel, Field
except ImportError:
    BaseModel = None  # type: ignore[misc,assignment]
    Field = None  # type: ignore[misc,assignment]


# ──────────────────────────────────────────────────────
# SentinelCrewTool — wraps MockTool as a CrewAI BaseTool
# ──────────────────────────────────────────────────────


class SentinelCrewTool:
    """Wraps a sentinel MockTool as a CrewAI-compatible tool.

    Exposes ``run(**kwargs)`` which is CrewAI's BaseTool invocation protocol.
    The tool delegates to the mock for response generation and records every
    call into the provided AgentTrace.

    This class duck-types enough of CrewAI's BaseTool interface to work
    without requiring crewai to be installed. When crewai IS installed,
    the tool can be passed directly to a CrewAI Agent's ``tools`` list.

    Args:
        mock: The sentinel MockTool that provides canned responses.
        trace: AgentTrace to record all tool calls into.
        name: Tool name (used by CrewAI for identification).
        description: Tool description (shown to the LLM).
    """

    def __init__(
        self,
        mock: MockTool,
        trace: AgentTrace,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        self._mock = mock
        self._trace = trace
        self.name: str = name or mock.name
        self.description: str = description or f"Sentinel mock tool: {self.name}"

    @property
    def mock(self) -> MockTool:
        """Access the underlying sentinel MockTool."""
        return self._mock

    @property
    def trace(self) -> AgentTrace:
        """Access the AgentTrace this adapter records into."""
        return self._trace

    def run(self, **kwargs: Any) -> Any:
        """Execute the tool — CrewAI's BaseTool invocation protocol.

        Delegates to the mock tool and records the call into the trace.
        Compatible with CrewAI's ``tool.run(**kwargs)`` pattern.

        Returns the mock tool's response (or raises its configured error).
        """
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

    def _run(self, **kwargs: Any) -> Any:
        """Alias for run() — some CrewAI patterns call _run directly."""
        return self.run(**kwargs)

    def reset_calls(self) -> None:
        """Clear recorded calls on the mock tool."""
        self._mock.calls.clear()

    def __repr__(self) -> str:
        return (
            f"SentinelCrewTool(name={self.name!r}, "
            f"calls={self._mock.call_count})"
        )


# ──────────────────────────────────────────────────────
# CrewAgentWrapper — wraps a CrewAI Crew with sentinel mocking
# ──────────────────────────────────────────────────────


class CrewAgentWrapper:
    """Wraps a CrewAI Crew with sentinel tool mocking.

    Intercepts the crew's tool execution path and replaces all tool calls
    with sentinel MockTools. The crew's core LLM reasoning loop is untouched
    — only the tool layer is replaced.

    Note:
        This wrapper provides the plumbing for tool interception. For full
        integration testing, the caller should wire the adapter tools into
        the crew's agents before kickoff. This wrapper handles the bookkeeping
        of adapters and trace.
    """

    def __init__(
        self,
        crew: Any,
        tool_map: Dict[str, MockTool],
        trace: AgentTrace,
    ) -> None:
        self._crew = crew
        self._trace = trace
        self._adapters: Dict[str, SentinelCrewTool] = {}

        # Create an adapter for each mock tool
        for tool_name, mock in tool_map.items():
            self._adapters[tool_name] = SentinelCrewTool(
                mock=mock,
                trace=trace,
                name=tool_name,
            )

    @property
    def adapters(self) -> Dict[str, SentinelCrewTool]:
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

    def get_adapter(self, name: str) -> Optional[SentinelCrewTool]:
        """Get the adapter tool for a given name."""
        return self._adapters.get(name)

    def get_tool_list(self) -> List[SentinelCrewTool]:
        """Get all adapters as a list (for passing to CrewAI Agent.tools)."""
        return list(self._adapters.values())

    def __repr__(self) -> str:
        return (
            f"CrewAgentWrapper(crew={type(self._crew).__name__}, "
            f"tools={list(self._adapters.keys())})"
        )


def wrap_crew_agent(
    crew: Any,
    tool_map: Dict[str, MockTool],
    trace: AgentTrace,
) -> CrewAgentWrapper:
    """Wrap a CrewAI Crew with sentinel tool mocking.

    Creates a wrapper around the crew that:
    1. Creates SentinelCrewTool adapters for each mock tool
    2. Records every call into the AgentTrace
    3. Provides get_tool_list() for easy wiring into CrewAI agents

    Args:
        crew: A CrewAI Crew instance.
        tool_map: Mapping of tool name → sentinel MockTool.
        trace: AgentTrace to record all calls into.

    Returns:
        CrewAgentWrapper with adapters ready for wiring.

    Example:
        from sentinel.adapters.crewai import wrap_crew_agent
        from sentinel.env import MockTool

        wrapper = wrap_crew_agent(
            crew=my_crew,
            tool_map={
                "search": MockTool("search", response=SEARCH_RESULTS),
                "email": MockTool("email", response="sent"),
            },
            trace=trace,
        )
        # Wire into crew agents:
        for agent in my_crew.agents:
            agent.tools = wrapper.get_tool_list()
    """
    return CrewAgentWrapper(
        crew=crew,
        tool_map=tool_map,
        trace=trace,
    )
