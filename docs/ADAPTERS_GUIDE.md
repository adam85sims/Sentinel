# Adapters Guide — Testing Real Agent Frameworks

> Sentinel works with any agent framework through adapters.
> Here's how to use them and write custom ones.

## Built-in Adapters

### LangChain

```python
from sentinel.adapters.langchain import SentinelToolAdapter, wrap_agent
from sentinel.env import MockTool
from sentinel.models import AgentTrace

# Option 1: Wrap individual tools
trace = AgentTrace()
adapter = SentinelToolAdapter(
    mock=MockTool("search", response="results"),
    trace=trace,
    base_tool=your_langchain_tool,  # Real @tool-decorated function
)

# Option 2: Wrap entire agent
wrapped = wrap_agent(
    agent=your_agent,
    tool_map={
        "search": MockTool("search", response="results"),
        "email": MockTool("email", response="sent"),
    },
    trace=trace,
)

# Use the wrapped agent
result = wrapped.invoke({"messages": [HumanMessage(content="Find info")]})
```

**What it preserves:**
- Tool name, description, args schema from real LangChain tools
- Agent's core LLM reasoning loop (untouched)
- All tool calls recorded in AgentTrace

**What it replaces:**
- Tool execution → delegated to sentinel MockTools
- External API calls → mocked responses

### CrewAI

```python
from sentinel.adapters.crewai import SentinelCrewTool, wrap_crew_agent
from sentinel.env import MockTool
from sentinel.models import AgentTrace

trace = AgentTrace()

# Wrap a crew agent
wrapped = wrap_crew_agent(
    agent=your_crew_agent,
    tool_map={
        "search": MockTool("search", response="results"),
    },
    trace=trace,
)

# Access individual adapters
adapter = wrapped.get_adapter("search")
print(f"Calls made: {adapter.mock.call_count}")
```

### OpenAI Agents SDK

```python
from sentinel.adapters.openai import wrap_agent
from sentinel.env import MockTool
from sentinel.models import AgentTrace

trace = AgentTrace()

wrapped = wrap_agent(
    agent=your_openai_agent,
    tool_map={
        "search": MockTool("search", response="results"),
    },
    trace=trace,
)
```

### Generic (Any Framework)

```python
from sentinel.adapters.generic import HookAdapter, wrap_callable
from sentinel.env import MockTool
from sentinel.models import AgentTrace

trace = AgentTrace()

# Wrap any callable
adapter = HookAdapter(
    mock=MockTool("search", response="results"),
    trace=trace,
)

# Add hooks for preprocessing/postprocessing
adapter.add_before_hook(lambda kwargs: {**kwargs, "query": kwargs["query"].strip()})
adapter.add_after_hook(lambda result: {"data": result, "cached": False})

# Or use the decorator
@wrap_callable(trace=trace)
def my_tool(query: str) -> str:
    return f"Results for {query}"
```

## Writing Custom Adapters

### The Protocol

An adapter must:

1. Accept a `MockTool` for response generation
2. Accept an `AgentTrace` for call recording
3. Expose `invoke()` and `__call__()` interfaces
4. Record every call (success or failure) into the trace

### Template

```python
from sentinel.env import MockTool
from sentinel.models import AgentTrace, ToolCall
import time


class MyFrameworkAdapter:
    """Adapter for [Framework Name]."""

    def __init__(self, mock: MockTool, trace: AgentTrace, framework_tool=None):
        self._mock = mock
        self._trace = trace
        self._tool = framework_tool

    @property
    def name(self) -> str:
        return self._mock.name

    def invoke(self, **kwargs) -> Any:
        """Invoke the tool through the mock."""
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
            self._trace.add_tool_call(ToolCall(
                tool_name=self._mock.name,
                arguments=kwargs,
                result=result,
                duration_ms=duration_ms,
                error=error_msg,
            ))

        return result

    def __call__(self, **kwargs) -> Any:
        return self.invoke(**kwargs)
```

### Integration Checklist

- [ ] Adapter records all calls (success + failure) into AgentTrace
- [ ] Adapter preserves framework tool metadata (name, description, args)
- [ ] Adapter works with sentinel's chaos injectors (wrap the MockTool)
- [ ] Adapter works with sentinel's assertions (reads from AgentTrace)
- [ ] Adapter handles framework-specific input formats (dict, string, etc.)
- [ ] Adapter type-checks framework tools (raises TypeError for wrong type)

## Testing Adapters

```python
import pytest
from sentinel.adapters.langchain import SentinelToolAdapter
from sentinel.env import MockTool
from sentinel.models import AgentTrace


class TestMyAdapter:
    def test_records_successful_call(self):
        trace = AgentTrace()
        mock = MockTool("my_tool", response="ok")
        adapter = SentinelToolAdapter(mock=mock, trace=trace)

        result = adapter.invoke({"query": "test"})

        assert result == "ok"
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].tool_name == "my_tool"
        assert trace.tool_calls[0].error is None

    def test_records_failed_call(self):
        trace = AgentTrace()
        mock = MockTool("my_tool", side_effect=ValueError("bad input"))
        adapter = SentinelToolAdapter(mock=mock, trace=trace)

        with pytest.raises(ValueError):
            adapter.invoke({"query": "test"})

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].error == "bad input"

    def test_works_with_chaos(self):
        from sentinel.chaos import ToolFailureInjector

        trace = AgentTrace()
        mock = MockTool("my_tool", response="ok")

        injector = ToolFailureInjector(
            tool_name="my_tool",
            failure_type="error",
            probability=1.0,
        )
        injector.wrap(mock)

        adapter = SentinelToolAdapter(mock=mock, trace=trace)

        with pytest.raises(Exception):
            adapter.invoke({"query": "test"})

        assert trace.tool_calls[0].error is not None
```
