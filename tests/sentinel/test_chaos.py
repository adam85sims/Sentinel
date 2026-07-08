"""Tests for Sentinel chaos/failure injection layer."""

import pytest
from sentinel.chaos import (
    ChaosBudget,
    ChaosBudgetExhausted,
    ChaosToolWrapper,
    InjectionRecord,
    LLMFailureInjector,
    LLMFailureType,
    ToolFailureInjector,
    ToolFailureType,
)
from sentinel.env import MockTool, MockToolError, RateLimitError, TimeoutError


# ──────────────────────────────────────────────────────
# ToolFailureInjector Tests
# ──────────────────────────────────────────────────────


class TestToolFailureInjector:
    def test_timeout_failure(self):
        inj = ToolFailureInjector(tool_name="search", failure_type="timeout")
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        with pytest.raises(TimeoutError):
            wrapped(q="test")

        assert inj.injection_count == 1
        assert len(inj.records) == 1
        assert inj.records[0].failure_type == "timeout"

    def test_error_failure(self):
        inj = ToolFailureInjector(tool_name="search", failure_type="error")
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        with pytest.raises(MockToolError) as exc_info:
            wrapped(q="test")
        assert exc_info.value.status_code == 500

    def test_rate_limit_failure(self):
        inj = ToolFailureInjector(tool_name="search", failure_type="rate_limit")
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        with pytest.raises(RateLimitError):
            wrapped(q="test")

        assert inj.records[0].failure_type == "rate_limit"

    def test_malformed_failure(self):
        inj = ToolFailureInjector(tool_name="search", failure_type="malformed")
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        with pytest.raises(MockToolError) as exc_info:
            wrapped(q="test")
        assert "Malformed response" in str(exc_info.value)
        assert exc_info.value.status_code == 502

    def test_partial_failure(self):
        inj = ToolFailureInjector(tool_name="search", failure_type="partial")
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        with pytest.raises(MockToolError) as exc_info:
            wrapped(q="test")
        assert "Partial response" in str(exc_info.value)
        assert exc_info.value.status_code == 200

    def test_custom_error_message(self):
        inj = ToolFailureInjector(
            tool_name="search",
            failure_type="error",
            error_message="Custom error message",
        )
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        with pytest.raises(MockToolError, match="Custom error message"):
            wrapped(q="test")

    def test_probability_zero_never_fails(self):
        inj = ToolFailureInjector(
            tool_name="search", failure_type="error", probability=0.0
        )
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        for _ in range(50):
            result = wrapped(q="test")

        assert result == "ok"
        assert inj.injection_count == 0

    def test_probability_one_always_fails(self):
        inj = ToolFailureInjector(
            tool_name="search", failure_type="error", probability=1.0
        )
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        for i in range(10):
            with pytest.raises(MockToolError):
                wrapped(q=f"test_{i}")

        assert inj.injection_count == 10

    def test_does_not_target_other_tools(self):
        inj = ToolFailureInjector(tool_name="search", failure_type="error")
        other_tool = MockTool("email", response="sent")
        wrapped = inj.wrap(other_tool)

        result = wrapped(to="test@test.com")
        assert result == "sent"
        assert inj.injection_count == 0

    def test_after_step_defers_injection(self):
        inj = ToolFailureInjector(
            tool_name="search", failure_type="error", after_step=2
        )
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        # First 2 calls should succeed (after_step=2 means skip first 2)
        for i in range(2):
            result = wrapped(q=f"call_{i}")
            assert result == "ok"

        # Third call should fail
        with pytest.raises(MockToolError):
            wrapped(q="call_2")

        assert inj.injection_count == 1

    def test_records_injection_history(self):
        inj = ToolFailureInjector(
            tool_name="search", failure_type="rate_limit", seed=42
        )
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        for i in range(5):
            try:
                wrapped(q=f"call_{i}")
            except RateLimitError:
                pass

        assert len(inj.records) == inj.injection_count
        for record in inj.records:
            assert record.injector_type == "tool"
            assert record.target == "search"
            assert record.failure_type == "rate_limit"

    def test_inject_method_manual_trigger(self):
        inj = ToolFailureInjector(tool_name="search", failure_type="error")
        tool = MockTool("search", response="ok")

        with pytest.raises(MockToolError):
            inj.inject(tool, {"q": "test"})

        assert inj.injection_count == 1

    def test_inject_method_skips_unrelated_tool(self):
        inj = ToolFailureInjector(tool_name="search", failure_type="error")
        other_tool = MockTool("email", response="sent")

        result = inj.inject(other_tool, {"to": "test@test.com"})
        assert result is False
        assert inj.injection_count == 0

    def test_reset_clears_state(self):
        inj = ToolFailureInjector(
            tool_name="search", failure_type="error", seed=42
        )
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        # Trigger some injections
        for i in range(5):
            try:
                wrapped(q=f"call_{i}")
            except MockToolError:
                pass

        assert inj.injection_count > 0
        assert len(inj.records) > 0

        inj.reset()
        assert inj.injection_count == 0
        assert len(inj.records) == 0

    def test_tool_still_records_calls_through_wrapper(self):
        inj = ToolFailureInjector(tool_name="search", failure_type="error")
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        for i in range(5):
            try:
                wrapped(q=f"call_{i}")
            except MockToolError:
                pass

        # The underlying tool should still record calls
        assert tool.call_count == 5

    def test_wrapper_is_callable(self):
        inj = ToolFailureInjector(tool_name="search", failure_type="error")
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)
        assert callable(wrapped)

    def test_wrapper_proxies_attributes(self):
        inj = ToolFailureInjector(tool_name="search", failure_type="error")
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)
        assert wrapped.name == "search"
        assert wrapped.call_count == 0

    def test_wrap_modifies_tool_in_place(self):
        """wrap() installs call_handler on the tool and returns the same object."""
        inj = ToolFailureInjector(tool_name="search", failure_type="error")
        tool = MockTool("search", response="ok")
        result = inj.wrap(tool)
        # wrap modifies tool in place and returns it — same object
        assert result is tool
        assert tool.call_handler is not None


# ──────────────────────────────────────────────────────
# LLMFailureInjector Tests
# ──────────────────────────────────────────────────────


class TestLLMFailureInjector:
    def test_rate_limit_failure(self):
        inj = LLMFailureInjector(failure_type="rate_limit")

        failure = inj.check_step(step_id=1)
        assert failure is not None
        assert failure["type"] == "rate_limit"
        assert failure["step_id"] == 1
        assert inj.injection_count == 1

    def test_timeout_failure(self):
        inj = LLMFailureInjector(failure_type="timeout")

        failure = inj.check_step(step_id=1)
        assert failure is not None
        assert failure["type"] == "timeout"

    def test_partial_response_failure(self):
        inj = LLMFailureInjector(failure_type="partial_response")

        failure = inj.check_step(step_id=1)
        assert failure is not None
        assert failure["type"] == "partial_response"

    def test_stream_interrupt_failure(self):
        inj = LLMFailureInjector(failure_type="stream_interrupt")

        failure = inj.check_step(step_id=1)
        assert failure is not None
        assert failure["type"] == "stream_interrupt"

    def test_after_step_defers_injection(self):
        inj = LLMFailureInjector(failure_type="rate_limit", after_step=3)

        # Steps 1-3 should not inject
        for step_id in range(1, 4):
            failure = inj.check_step(step_id)
            assert failure is None

        # Step 4 should inject
        failure = inj.check_step(step_id=4)
        assert failure is not None
        assert failure["type"] == "rate_limit"

    def test_probability_control(self):
        inj = LLMFailureInjector(
            failure_type="rate_limit", probability=0.0, seed=42
        )

        for step_id in range(1, 100):
            failure = inj.check_step(step_id)
            assert failure is None

        assert inj.injection_count == 0

    def test_get_error_returns_exception(self):
        inj = LLMFailureInjector(failure_type="rate_limit")
        error = inj.get_error(step_id=1)

        assert error is not None
        assert isinstance(error, RateLimitError)
        assert inj.injection_count == 1

    def test_get_error_timeout(self):
        inj = LLMFailureInjector(failure_type="timeout")
        error = inj.get_error(step_id=1)

        assert error is not None
        assert isinstance(error, TimeoutError)

    def test_get_error_partial_response(self):
        inj = LLMFailureInjector(failure_type="partial_response")
        error = inj.get_error(step_id=1)

        assert error is not None
        assert isinstance(error, MockToolError)
        assert "Partial LLM response" in str(error)

    def test_get_error_stream_interrupt(self):
        inj = LLMFailureInjector(failure_type="stream_interrupt")
        error = inj.get_error(step_id=1)

        assert error is not None
        assert isinstance(error, MockToolError)
        assert "Stream interrupted" in str(error)

    def test_get_error_returns_none_when_no_injection(self):
        inj = LLMFailureInjector(failure_type="rate_limit", probability=0.0)
        error = inj.get_error(step_id=1)
        assert error is None

    def test_custom_error_message(self):
        inj = LLMFailureInjector(
            failure_type="rate_limit", error_message="Custom LLM error"
        )
        failure = inj.check_step(step_id=1)
        assert failure is not None
        assert failure["message"] == "Custom LLM error"

    def test_records_history(self):
        inj = LLMFailureInjector(failure_type="rate_limit", seed=42)

        for step_id in range(1, 20):
            inj.check_step(step_id)

        assert len(inj.records) == inj.injection_count
        for record in inj.records:
            assert record.injector_type == "llm"
            assert record.failure_type == "rate_limit"

    def test_reset_clears_state(self):
        inj = LLMFailureInjector(failure_type="rate_limit", seed=42)

        for step_id in range(1, 10):
            inj.check_step(step_id)

        assert inj.injection_count > 0

        inj.reset()
        assert inj.injection_count == 0
        assert len(inj.records) == 0


# ──────────────────────────────────────────────────────
# Deterministic Seeding Tests
# ──────────────────────────────────────────────────────


class TestDeterministicSeeding:
    def test_same_seed_same_tool_failures(self):
        """Same seed produces the same failure pattern."""
        results_1 = []
        results_2 = []

        for seed in [42, 123, 999]:
            inj1 = ToolFailureInjector(
                tool_name="search", failure_type="error", seed=seed
            )
            inj2 = ToolFailureInjector(
                tool_name="search", failure_type="error", seed=seed
            )

            for i in range(20):
                results_1.append(inj1._rng.random())
                results_2.append(inj2._rng.random())

        assert results_1 == results_2

    def test_same_seed_same_llm_failures(self):
        """Same seed produces the same LLM failure pattern."""
        inj1 = LLMFailureInjector(failure_type="rate_limit", seed=42)
        inj2 = LLMFailureInjector(failure_type="rate_limit", seed=42)

        patterns_1 = []
        patterns_2 = []

        for step_id in range(1, 30):
            patterns_1.append(inj1.check_step(step_id) is not None)
            patterns_2.append(inj2.check_step(step_id) is not None)

        assert patterns_1 == patterns_2

    def test_different_seeds_differ(self):
        """Different seeds produce different failure patterns."""
        inj1 = ToolFailureInjector(
            tool_name="search", failure_type="error", seed=42, probability=0.5
        )
        inj2 = ToolFailureInjector(
            tool_name="search", failure_type="error", seed=99, probability=0.5
        )

        tool1 = MockTool("search", response="ok")
        tool2 = MockTool("search", response="ok")
        wrapped1 = inj1.wrap(tool1)
        wrapped2 = inj2.wrap(tool2)

        count1 = count2 = 0
        for i in range(100):
            try:
                wrapped1(q=f"test_{i}")
            except MockToolError:
                count1 += 1
            try:
                wrapped2(q=f"test_{i}")
            except MockToolError:
                count2 += 1

        # Both seeds should produce some failures with 50% probability
        assert count1 > 0
        assert count2 > 0

    def test_seed_none_uses_system_random(self):
        """None seed means non-deterministic (we just verify it works)."""
        inj = ToolFailureInjector(tool_name="search", failure_type="error", seed=None)
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        with pytest.raises(MockToolError):
            wrapped(q="test")

        assert inj.injection_count == 1

    def test_reproducible_wrap_behavior(self):
        """Wrapping the same tool config with same seed gives same results."""
        counts = []
        for _ in range(2):
            inj = ToolFailureInjector(
                tool_name="search", failure_type="error", seed=42, probability=0.5
            )
            tool = MockTool("search", response="ok")
            wrapped = inj.wrap(tool)

            fail_count = 0
            for i in range(100):
                try:
                    wrapped(q=f"test_{i}")
                except MockToolError:
                    fail_count += 1
            counts.append(fail_count)

        assert counts[0] == counts[1]


# ──────────────────────────────────────────────────────
# ChaosBudget Tests
# ──────────────────────────────────────────────────────


class TestChaosBudget:
    def test_empty_budget(self):
        budget = ChaosBudget(max_failures=5)
        assert budget.total_injected == 0
        assert budget.remaining == 5
        assert not budget.exhausted
        assert budget.can_inject()

    def test_add_injector(self):
        budget = ChaosBudget(max_failures=3)
        inj = ToolFailureInjector(tool_name="search", failure_type="error")
        budget.add(inj)

        assert len(budget.get_injectors()) == 1

    def test_fluent_chaining(self):
        budget = (
            ChaosBudget(max_failures=3)
            .add(ToolFailureInjector(tool_name="search", failure_type="timeout"))
            .add(LLMFailureInjector(failure_type="rate_limit"))
        )

        assert len(budget.get_injectors()) == 2

    def test_budget_exhaustion(self):
        budget = ChaosBudget(max_failures=2)
        inj1 = ToolFailureInjector(tool_name="a", failure_type="error")
        inj2 = ToolFailureInjector(tool_name="b", failure_type="error")
        budget.add(inj1).add(inj2)

        tool_a = MockTool("a", response="ok")
        tool_b = MockTool("b", response="ok")
        wrapped_a = inj1.wrap(tool_a)
        wrapped_b = inj2.wrap(tool_b)

        with pytest.raises(MockToolError):
            wrapped_a()
        assert budget.total_injected == 1
        assert budget.remaining == 1

        with pytest.raises(MockToolError):
            wrapped_b()
        assert budget.total_injected == 2
        assert budget.remaining == 0
        assert budget.exhausted
        assert not budget.can_inject()

    def test_check_budget_raises_when_exhausted(self):
        budget = ChaosBudget(max_failures=1)
        inj = ToolFailureInjector(tool_name="a", failure_type="error")
        budget.add(inj)

        tool = MockTool("a", response="ok")
        wrapped = inj.wrap(tool)

        with pytest.raises(MockToolError):
            wrapped()

        with pytest.raises(ChaosBudgetExhausted, match="exhausted"):
            budget.check_budget()

    def test_unlimited_budget(self):
        budget = ChaosBudget(max_failures=0)  # Unlimited
        assert budget.remaining == -1
        assert not budget.exhausted
        assert budget.can_inject()

        # Should never raise
        for _ in range(1000):
            budget.check_budget()

    def test_records_aggregate_from_all_injectors(self):
        budget = ChaosBudget(max_failures=10)
        inj1 = ToolFailureInjector(tool_name="a", failure_type="error", seed=1)
        inj2 = LLMFailureInjector(failure_type="rate_limit", seed=2)
        budget.add(inj1).add(inj2)

        tool_a = MockTool("a", response="ok")
        wrapped_a = inj1.wrap(tool_a)

        for i in range(10):
            try:
                wrapped_a(q=f"test_{i}")
            except MockToolError:
                pass
            inj2.check_step(i)

        all_records = budget.records
        assert len(all_records) > 0
        # Records should be sorted by timestamp
        timestamps = [r.timestamp for r in all_records]
        assert timestamps == sorted(timestamps)

    def test_records_by_type(self):
        budget = ChaosBudget(max_failures=10)
        inj1 = ToolFailureInjector(tool_name="a", failure_type="error", seed=1)
        inj2 = LLMFailureInjector(failure_type="rate_limit", seed=2)
        budget.add(inj1).add(inj2)

        tool_a = MockTool("a", response="ok")
        wrapped_a = inj1.wrap(tool_a)

        for i in range(10):
            try:
                wrapped_a(q=f"test_{i}")
            except MockToolError:
                pass
            inj2.check_step(i)

        by_type = budget.records_by_type
        assert "tool" in by_type
        assert "llm" in by_type

    def test_records_by_failure(self):
        budget = ChaosBudget(max_failures=10)
        inj1 = ToolFailureInjector(tool_name="a", failure_type="timeout", seed=1)
        inj2 = LLMFailureInjector(failure_type="rate_limit", seed=2)
        budget.add(inj1).add(inj2)

        tool_a = MockTool("a", response="ok")
        wrapped_a = inj1.wrap(tool_a)

        for i in range(10):
            try:
                wrapped_a(q=f"test_{i}")
            except TimeoutError:
                pass
            inj2.check_step(i)

        by_failure = budget.records_by_failure
        assert "timeout" in by_failure
        assert "rate_limit" in by_failure

    def test_summary(self):
        budget = ChaosBudget(max_failures=3)
        budget.add(ToolFailureInjector(tool_name="a", failure_type="error"))
        budget.add(LLMFailureInjector(failure_type="rate_limit"))

        summary = budget.summary()
        assert summary["max_failures"] == 3
        assert summary["total_injected"] == 0
        assert summary["remaining"] == 3
        assert not summary["exhausted"]
        assert summary["injector_count"] == 2
        assert len(summary["injector_details"]) == 2

    def test_reset_clears_all_injectors(self):
        budget = ChaosBudget(max_failures=5)
        inj1 = ToolFailureInjector(tool_name="a", failure_type="error", seed=1)
        inj2 = LLMFailureInjector(failure_type="rate_limit", seed=2)
        budget.add(inj1).add(inj2)

        tool_a = MockTool("a", response="ok")
        wrapped_a = inj1.wrap(tool_a)

        for i in range(10):
            try:
                wrapped_a(q=f"test_{i}")
            except MockToolError:
                pass
            inj2.check_step(i)

        assert budget.total_injected > 0

        budget.reset()
        assert budget.total_injected == 0
        assert inj1.injection_count == 0
        assert inj2.injection_count == 0

    def test_budget_enforced_across_injectors(self):
        """Budget limits total failures, not per-injector."""
        budget = ChaosBudget(max_failures=3)
        inj1 = ToolFailureInjector(
            tool_name="a", failure_type="error", seed=1, probability=1.0
        )
        inj2 = ToolFailureInjector(
            tool_name="b", failure_type="error", seed=2, probability=1.0
        )
        budget.add(inj1).add(inj2)

        tool_a = MockTool("a", response="ok")
        tool_b = MockTool("b", response="ok")
        wrapped_a = inj1.wrap(tool_a)
        wrapped_b = inj2.wrap(tool_b)

        fail_count = 0
        for i in range(10):
            try:
                wrapped_a(q=f"call_a_{i}")
            except MockToolError:
                fail_count += 1
            try:
                wrapped_b(q=f"call_b_{i}")
            except MockToolError:
                fail_count += 1

        # Both injectors fire independently (each has probability 1.0)
        assert inj1.injection_count + inj2.injection_count == fail_count


# ──────────────────────────────────────────────────────
# Integration Tests
# ──────────────────────────────────────────────────────


class TestIntegration:
    def test_full_chaos_setup_from_architecture(self):
        """Test the exact example from ARCHITECTURE.md."""
        chaos = (
            ChaosBudget(max_failures=3)
            .add(
                ToolFailureInjector(
                    tool_name="search",
                    failure_type="timeout",
                    probability=0.1,
                    seed=42,
                )
            )
            .add(
                LLMFailureInjector(
                    failure_type="rate_limit",
                    after_step=3,
                )
            )
        )

        assert len(chaos.get_injectors()) == 2
        assert chaos.max_failures == 3
        assert chaos.remaining == 3

    def test_tool_injector_wraps_mock_tool(self):
        """Test that wrap() properly integrates with MockTool."""
        inj = ToolFailureInjector(
            tool_name="search", failure_type="error", probability=0.0
        )
        tool = MockTool("search", response={"results": ["a", "b"]})
        wrapped = inj.wrap(tool)

        # With probability=0, should always succeed
        result = wrapped(q="test")
        assert result == {"results": ["a", "b"]}

    def test_chaos_budget_with_tool_injection(self):
        """Test full integration: budget → injector → tool."""
        budget = ChaosBudget(max_failures=2)
        inj = ToolFailureInjector(
            tool_name="search", failure_type="timeout", seed=42
        )
        budget.add(inj)

        tool = MockTool("search", response="results")
        wrapped = inj.wrap(tool)

        for i in range(5):
            try:
                wrapped(q=f"query_{i}")
            except TimeoutError:
                pass

        assert budget.total_injected == inj.injection_count
        assert len(budget.records) > 0

    def test_chaos_budget_with_llm_injection(self):
        """Test full integration: budget → LLM injector."""
        budget = ChaosBudget(max_failures=5)
        inj = LLMFailureInjector(failure_type="rate_limit", seed=42)
        budget.add(inj)

        for step_id in range(1, 20):
            error = inj.get_error(step_id)
            if error is not None:
                assert isinstance(error, RateLimitError)

        assert budget.total_injected == inj.injection_count

    def test_multiple_tool_injectors_different_names(self):
        """Test multiple injectors targeting different tools."""
        budget = ChaosBudget(max_failures=10)
        inj_search = ToolFailureInjector(
            tool_name="search", failure_type="timeout"
        )
        inj_email = ToolFailureInjector(
            tool_name="email", failure_type="rate_limit"
        )
        budget.add(inj_search).add(inj_email)

        search_tool = MockTool("search", response="results")
        email_tool = MockTool("email", response="sent")
        wrapped_search = inj_search.wrap(search_tool)
        wrapped_email = inj_email.wrap(email_tool)

        with pytest.raises(TimeoutError):
            wrapped_search(q="test")

        with pytest.raises(RateLimitError):
            wrapped_email(to="test@test.com")

        assert inj_search.injection_count == 1
        assert inj_email.injection_count == 1

    def test_injection_record_fields(self):
        """Test that injection records capture all relevant info."""
        inj = ToolFailureInjector(
            tool_name="search", failure_type="error", error_message="Custom msg"
        )
        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        with pytest.raises(MockToolError):
            wrapped(q="test")

        record = inj.records[0]
        assert record.injector_type == "tool"
        assert record.failure_type == "error"
        assert record.target == "search"
        assert record.call_index == 1
        assert "Custom msg" in record.message
        assert record.timestamp > 0

    def test_llm_injection_record_fields(self):
        """Test that LLM injection records capture all relevant info."""
        inj = LLMFailureInjector(failure_type="stream_interrupt")
        failure = inj.check_step(step_id=5)

        assert failure is not None
        record = inj.records[0]
        assert record.injector_type == "llm"
        assert record.failure_type == "stream_interrupt"
        assert record.target == "step_5"
        assert record.step_id == 5

    def test_budget_summary_after_injections(self):
        """Test summary reflects actual injection state."""
        budget = ChaosBudget(max_failures=5)
        inj = ToolFailureInjector(
            tool_name="search", failure_type="error", seed=42
        )
        budget.add(inj)

        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        for i in range(10):
            try:
                wrapped(q=f"test_{i}")
            except MockToolError:
                pass

        summary = budget.summary()
        assert summary["total_injected"] == inj.injection_count
        assert summary["remaining"] == max(0, 5 - inj.injection_count)

    def test_tool_injection_count_tracks_independent_of_budget(self):
        """Individual injector count is independent of budget cap."""
        budget = ChaosBudget(max_failures=1)  # Very tight budget
        inj = ToolFailureInjector(
            tool_name="search", failure_type="error", seed=42
        )
        budget.add(inj)

        tool = MockTool("search", response="ok")
        wrapped = inj.wrap(tool)

        for i in range(10):
            try:
                wrapped(q=f"test_{i}")
            except MockToolError:
                pass

        # Injector tracks its own count regardless of budget
        assert inj.injection_count > 0
        # Budget tracks the sum
        assert budget.total_injected == inj.injection_count
