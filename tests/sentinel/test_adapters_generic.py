"""Tests for Sentinel generic hook-based adapter."""

import pytest

from sentinel.adapters.generic import (
    HookAdapter,
    HookAdapterGroup,
    wrap_callable,
)
from sentinel.env import MockTool, MockToolError, RateLimitError
from sentinel.models import AgentTrace


class TestHookAdapter:
    def test_basic_execute_with_mock(self):
        """execute() delegates to mock and records calls."""
        trace = AgentTrace()
        mock = MockTool("search", response={"results": ["a", "b"]})
        adapter = HookAdapter(mock=mock, trace=trace)

        result = adapter.execute(query="test")

        assert result == {"results": ["a", "b"]}
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].tool_name == "search"
        assert trace.tool_calls[0].arguments == {"query": "test"}

    def test_basic_execute_with_fn(self):
        """execute() delegates to original function when no mock."""
        trace = AgentTrace()

        def my_fn(**kwargs):
            return {"computed": kwargs.get("x", 0) * 2}

        adapter = HookAdapter(fn=my_fn, trace=trace, name="doubler")

        result = adapter.execute(x=5)

        assert result == {"computed": 10}
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].tool_name == "doubler"

    def test_requires_mock_or_fn(self):
        """Raises ValueError when neither mock nor fn is provided."""
        trace = AgentTrace()
        with pytest.raises(ValueError, match="Either mock or fn"):
            HookAdapter(trace=trace)

    def test_call_interface(self):
        """__call__ delegates to execute."""
        trace = AgentTrace()
        mock = MockTool("email", response="sent")
        adapter = HookAdapter(mock=mock, trace=trace)

        result = adapter(to="alice@example.com")

        assert result == "sent"
        assert len(trace.tool_calls) == 1

    def test_error_records_and_reraises(self):
        """Errors are recorded in trace and re-raised."""
        trace = AgentTrace()
        mock = MockTool("fail_tool", side_effect=RateLimitError("slow down"))
        adapter = HookAdapter(mock=mock, trace=trace)

        with pytest.raises(RateLimitError, match="slow down"):
            adapter.execute(q="test")

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].error == "slow down"
        assert trace.tool_calls[0].result is None

    def test_multiple_calls_tracked(self):
        """Multiple calls are all tracked."""
        trace = AgentTrace()
        mock = MockTool("counter", response_fn=lambda n=0: {"count": n})
        adapter = HookAdapter(mock=mock, trace=trace)

        adapter.execute(n=1)
        adapter.execute(n=2)
        adapter.execute(n=3)

        assert len(trace.tool_calls) == 3
        assert [tc.arguments for tc in trace.tool_calls] == [
            {"n": 1}, {"n": 2}, {"n": 3},
        ]


class TestHookAdapterHooks:
    def test_before_hook_modifies_kwargs(self):
        """Before-hook transforms kwargs before execution."""
        trace = AgentTrace()
        mock = MockTool("tool", response_fn=lambda **kw: kw)
        adapter = HookAdapter(mock=mock, trace=trace)

        # Hook adds a default limit
        adapter.add_before_hook(lambda kwargs: {**kwargs, "limit": 10})

        result = adapter.execute(query="test")

        assert result == {"query": "test", "limit": 10}
        assert trace.tool_calls[0].arguments == {"query": "test", "limit": 10}

    def test_before_hook_chain(self):
        """Multiple before-hooks chain in registration order."""
        trace = AgentTrace()
        mock = MockTool("tool", response_fn=lambda **kw: kw)
        adapter = HookAdapter(mock=mock, trace=trace)

        adapter.add_before_hook(lambda kw: {**kw, "a": 1})
        adapter.add_before_hook(lambda kw: {**kw, "b": 2})

        result = adapter.execute()

        assert result == {"a": 1, "b": 2}

    def test_after_hook_modifies_result(self):
        """After-hook transforms result after execution."""
        trace = AgentTrace()
        mock = MockTool("tool", response={"data": [1, 2, 3, 4, 5]})
        adapter = HookAdapter(mock=mock, trace=trace)

        # Hook takes first 3 items
        adapter.add_after_hook(lambda result, kwargs: result["data"][:3])

        result = adapter.execute()

        assert result == [1, 2, 3]

    def test_after_hook_chain(self):
        """Multiple after-hooks chain in registration order."""
        trace = AgentTrace()
        mock = MockTool("tool", response=10)
        adapter = HookAdapter(mock=mock, trace=trace)

        adapter.add_after_hook(lambda result, kwargs: result * 2)  # 20
        adapter.add_after_hook(lambda result, kwargs: result + 5)  # 25

        result = adapter.execute()

        assert result == 25

    def test_after_hook_receives_kwargs(self):
        """After-hook receives the (processed) kwargs."""
        trace = AgentTrace()
        mock = MockTool("tool", response="ok")
        adapter = HookAdapter(mock=mock, trace=trace)

        received_kwargs = {}
        adapter.add_after_hook(lambda result, kwargs: (received_kwargs.update(kwargs), result)[1])

        adapter.execute(query="test", limit=5)

        assert received_kwargs == {"query": "test", "limit": 5}

    def test_error_hook_called_on_exception(self):
        """Error-hook is notified when the tool raises."""
        trace = AgentTrace()
        mock = MockTool("tool", side_effect=MockToolError("boom"))
        adapter = HookAdapter(mock=mock, trace=trace)

        errors = []
        adapter.add_error_hook(lambda exc, kwargs: errors.append(str(exc)))

        with pytest.raises(MockToolError):
            adapter.execute(q="test")

        assert errors == ["boom"]

    def test_error_hook_receives_kwargs(self):
        """Error-hook receives the kwargs that caused the error."""
        trace = AgentTrace()
        mock = MockTool("tool", side_effect=MockToolError("fail"))
        adapter = HookAdapter(mock=mock, trace=trace)

        received_kwargs = {}
        adapter.add_error_hook(lambda exc, kwargs: received_kwargs.update(kwargs))

        with pytest.raises(MockToolError):
            adapter.execute(q="test")

        assert received_kwargs == {"q": "test"}

    def test_error_hook_does_not_mask_exception(self):
        """Error-hook exceptions are swallowed; original exception propagates."""
        trace = AgentTrace()
        mock = MockTool("tool", side_effect=MockToolError("original"))
        adapter = HookAdapter(mock=mock, trace=trace)

        def bad_hook(exc, kwargs):
            raise RuntimeError("hook crashed")

        adapter.add_error_hook(bad_hook)

        with pytest.raises(MockToolError, match="original"):
            adapter.execute()

    def test_after_hook_not_called_on_error(self):
        """After-hooks are NOT called when the tool raises."""
        trace = AgentTrace()
        mock = MockTool("tool", side_effect=MockToolError("boom"))
        adapter = HookAdapter(mock=mock, trace=trace)

        after_called = []
        adapter.add_after_hook(lambda result, kwargs: after_called.append(True))

        with pytest.raises(MockToolError):
            adapter.execute()

        assert after_called == []

    def test_clear_hooks(self):
        """clear_hooks removes all registered hooks."""
        trace = AgentTrace()
        mock = MockTool("tool", response="ok")
        adapter = HookAdapter(mock=mock, trace=trace)

        adapter.add_before_hook(lambda kw: kw)
        adapter.add_after_hook(lambda r, kw: r)
        adapter.add_error_hook(lambda e, kw: None)

        assert len(adapter._before_hooks) == 1
        assert len(adapter._after_hooks) == 1
        assert len(adapter._error_hooks) == 1

        adapter.clear_hooks()

        assert len(adapter._before_hooks) == 0
        assert len(adapter._after_hooks) == 0
        assert len(adapter._error_hooks) == 0

    def test_reset_calls(self):
        """reset_calls clears mock tool's call history."""
        trace = AgentTrace()
        mock = MockTool("x", response="ok")
        adapter = HookAdapter(mock=mock, trace=trace)

        adapter.execute(a=1)
        adapter.execute(a=2)
        assert mock.call_count == 2

        adapter.reset_calls()
        assert mock.call_count == 0
        assert len(trace.tool_calls) == 2

    def test_default_name_from_mock(self):
        """Name defaults to mock.name."""
        trace = AgentTrace()
        mock = MockTool("my_tool", response="ok")
        adapter = HookAdapter(mock=mock, trace=trace)
        assert adapter.name == "my_tool"

    def test_default_name_from_fn(self):
        """Name defaults to fn.__name__ when no mock."""
        trace = AgentTrace()

        def my_function(**kwargs):
            return "ok"

        adapter = HookAdapter(fn=my_function, trace=trace)
        assert adapter.name == "my_function"

    def test_repr(self):
        """Repr shows adapter state."""
        trace = AgentTrace()
        mock = MockTool("search", response="ok")
        adapter = HookAdapter(mock=mock, trace=trace)

        r = repr(adapter)
        assert "HookAdapter" in r
        assert "name='search'" in r
        assert "source=mock" in r

    def test_repr_with_fn(self):
        """Repr shows fn source when no mock."""
        trace = AgentTrace()

        def my_fn(**kwargs):
            return "ok"

        adapter = HookAdapter(fn=my_fn, trace=trace)
        r = repr(adapter)
        assert "source=fn" in r


class TestWrapCallable:
    def test_decorator_creates_adapter(self):
        """@wrap_callable replaces function with HookAdapter."""
        trace = AgentTrace()
        mock = MockTool("search", response="results")

        @wrap_callable(mock=mock, trace=trace)
        def search(**kwargs):
            return "real_search"

        assert isinstance(search, HookAdapter)
        assert search.name == "search"

    def test_decorator_preserves_original_fn(self):
        """Original function is accessible via _original_fn."""
        trace = AgentTrace()
        mock = MockTool("tool", response="ok")

        def my_fn(**kwargs):
            return "original"

        wrapped = wrap_callable(mock=mock, trace=trace)(my_fn)

        assert wrapped._original_fn is my_fn

    def test_decorator_custom_name(self):
        """Custom name overrides function name."""
        trace = AgentTrace()
        mock = MockTool("tool", response="ok")

        @wrap_callable(mock=mock, trace=trace, name="custom_name")
        def my_fn(**kwargs):
            return "ok"

        assert my_fn.name == "custom_name"

    def test_decorator_uses_docstring(self):
        """Description defaults to function docstring."""
        trace = AgentTrace()
        mock = MockTool("tool", response="ok")

        @wrap_callable(mock=mock, trace=trace)
        def my_fn(**kwargs):
            """This is my tool."""
            return "ok"

        assert my_fn.description == "This is my tool."

    def test_decorator_callable(self):
        """Wrapped adapter is callable."""
        trace = AgentTrace()
        mock = MockTool("calc", response=42)

        @wrap_callable(mock=mock, trace=trace)
        def calc(**kwargs):
            return "real"

        result = calc(x=10)
        assert result == 42
        assert len(trace.tool_calls) == 1


class TestHookAdapterGroup:
    def test_add_adapter(self):
        """add() creates and registers an adapter."""
        trace = AgentTrace()
        group = HookAdapterGroup(trace=trace)
        mock = MockTool("search", response="results")

        adapter = group.add(mock=mock)

        assert adapter.name == "search"
        assert "search" in group.adapters

    def test_get_adapter(self):
        """get() returns adapter by name."""
        trace = AgentTrace()
        group = HookAdapterGroup(trace=trace)
        mock = MockTool("tool", response="ok")
        group.add(mock=mock)

        assert group.get("tool") is not None
        assert group.get("nonexistent") is None

    def test_shared_trace(self):
        """All adapters share the group's trace."""
        trace = AgentTrace()
        group = HookAdapterGroup(trace=trace)

        group.add(mock=MockTool("a", response="ok"))
        group.add(mock=MockTool("b", response="ok"))

        group.get("a").execute(q=1)
        group.get("b").execute(q=2)

        assert len(trace.tool_calls) == 2
        assert trace.tool_calls[0].tool_name == "a"
        assert trace.tool_calls[1].tool_name == "b"

    def test_apply_before_hook_to_all(self):
        """apply_before_hook_to_all registers on every adapter."""
        trace = AgentTrace()
        group = HookAdapterGroup(trace=trace)

        group.add(mock=MockTool("a", response_fn=lambda **kw: kw))
        group.add(mock=MockTool("b", response_fn=lambda **kw: kw))

        group.apply_before_hook_to_all(lambda kw: {**kw, "global": True})

        result_a = group.get("a").execute()
        result_b = group.get("b").execute()

        assert result_a == {"global": True}
        assert result_b == {"global": True}

    def test_apply_after_hook_to_all(self):
        """apply_after_hook_to_all registers on every adapter."""
        trace = AgentTrace()
        group = HookAdapterGroup(trace=trace)

        group.add(mock=MockTool("a", response=10))
        group.add(mock=MockTool("b", response=20))

        group.apply_after_hook_to_all(lambda result, kwargs: result * 2)

        assert group.get("a").execute() == 20
        assert group.get("b").execute() == 40

    def test_apply_error_hook_to_all(self):
        """apply_error_hook_to_all registers on every adapter."""
        trace = AgentTrace()
        group = HookAdapterGroup(trace=trace)

        group.add(mock=MockTool("a", side_effect=MockToolError("a_fail")))
        group.add(mock=MockTool("b", side_effect=MockToolError("b_fail")))

        errors = []
        group.apply_error_hook_to_all(lambda exc, kwargs: errors.append(str(exc)))

        with pytest.raises(MockToolError):
            group.get("a").execute()
        with pytest.raises(MockToolError):
            group.get("b").execute()

        assert sorted(errors) == ["a_fail", "b_fail"]

    def test_clear_all_hooks(self):
        """clear_all_hooks removes hooks from every adapter."""
        trace = AgentTrace()
        group = HookAdapterGroup(trace=trace)

        adapter = group.add(mock=MockTool("tool", response="ok"))
        adapter.add_before_hook(lambda kw: kw)
        adapter.add_after_hook(lambda r, kw: r)

        assert len(adapter._before_hooks) == 1

        group.clear_all_hooks()

        assert len(adapter._before_hooks) == 0
        assert len(adapter._after_hooks) == 0

    def test_repr(self):
        """Repr shows group state."""
        trace = AgentTrace()
        group = HookAdapterGroup(trace=trace)
        group.add(mock=MockTool("a", response="ok"))
        group.add(mock=MockTool("b", response="ok"))

        r = repr(group)
        assert "HookAdapterGroup" in r
        assert "tools=" in r
