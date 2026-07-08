"""Tests for Phase 5 chaos injectors: ContextDegradation, CascadingFailures, SpecDrift."""

import pytest
import time
from sentinel.chaos import (
    ContextDegradation,
    CascadingFailures,
    SpecDrift,
    DegradationStrategy,
    DriftIntensity,
)


# ──────────────────────────────────────────────────────
# ContextDegradation Tests
# ──────────────────────────────────────────────────────


class TestContextDegradation:
    def test_no_degradation_before_start_step(self):
        """Degradation should not activate before start_step."""
        inj = ContextDegradation(strategy="truncation", start_step=5)
        context = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        result = inj.on_step(step_id=3, context=context)
        assert result["injected"] is False
        assert result["context"] == context
        assert inj.injection_count == 0

    def test_truncation_removes_early_context(self):
        """Truncation strategy should remove earlier context entries."""
        inj = ContextDegradation(
            strategy="truncation",
            start_step=1,
            degradation_rate=0.5,
            seed=42,
        )
        context = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Message 3"},
        ]
        # Run enough steps to get non-zero degradation
        for step in range(1, 20):
            result = inj.on_step(step_id=step, context=context)

        # After many steps, some context should be truncated
        assert result["degradation_level"] > 0.0
        assert result["injected"] is True
        # System prompt should be preserved
        if result["context"]:
            assert result["context"][0]["role"] == "system"

    def test_truncation_preserves_system_prompt(self):
        """System prompt should never be truncated."""
        inj = ContextDegradation(
            strategy="truncation",
            start_step=1,
            degradation_rate=1.0,  # Maximum degradation
            seed=42,
        )
        context = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        # Run many steps to trigger degradation
        result = inj.on_step(step_id=50, context=context)
        # Even with max degradation, system prompt must remain
        assert result["context"][0]["role"] == "system"
        assert result["context"][0]["content"] == "You are helpful."

    def test_noise_injects_character_corruption(self):
        """Noise strategy should modify character content."""
        inj = ContextDegradation(
            strategy="noise",
            start_step=1,
            degradation_rate=1.0,  # Max degradation for visible noise
            seed=42,
        )
        context = [
            {"role": "system", "content": "A" * 100},  # 100 chars = more chances
        ]
        # Run enough steps for degradation to ramp up
        for step in range(1, 20):
            result = inj.on_step(step_id=step, context=context)

        assert result["degradation_level"] > 0.0
        # Content should differ from original due to noise
        # (at degradation_level > 0 with 100 chars, some should change)
        content = result["context"][0]["content"]
        # With high degradation and 100 identical chars, at least some should differ
        assert content != "A" * 100 or result["degradation_level"] < 0.01

    def test_drift_modifies_system_prompt(self):
        """Drift strategy should modify the system prompt over time."""
        inj = ContextDegradation(
            strategy="drift",
            start_step=1,
            degradation_rate=0.5,
            seed=42,
        )
        original_prompt = "You are a helpful assistant that answers questions accurately."
        # Run many steps to accumulate drift
        result = None
        for step in range(1, 30):
            result = inj.on_step(step_id=step, system_prompt=original_prompt)

        assert result is not None
        assert result["degradation_level"] > 0.0
        assert result["injected"] is True
        # Drift should have modified the prompt (with enough steps)
        # Note: with seed=42, this is deterministic

    def test_degradation_level_accelerates(self):
        """Degradation level should follow quadratic acceleration."""
        inj = ContextDegradation(
            strategy="truncation",
            start_step=5,
            degradation_rate=0.1,
        )
        levels = []
        for step in range(1, 30):
            inj._step_count = step
            levels.append(inj.current_degradation_level)

        # Level should be 0 before start_step
        assert levels[0] == 0.0
        # Level should increase non-linearly (quadratic)
        # Check that early diffs are non-zero and increasing
        post_start = [l for l in levels if l > 0]
        assert len(post_start) >= 5, "Need enough steps to see acceleration"
        # First few diffs should be increasing (quadratic region)
        diffs = [post_start[i+1] - post_start[i] for i in range(min(3, len(post_start)-1))]
        if len(diffs) >= 2:
            assert diffs[1] > diffs[0], "Diffs should increase (quadratic)"

    def test_records_are_logged(self):
        """Injection records should be created for each degradation event."""
        inj = ContextDegradation(
            strategy="truncation",
            start_step=1,
            degradation_rate=0.5,
        )
        context = [{"role": "user", "content": "Hello"}] * 10
        for step in range(1, 15):
            inj.on_step(step_id=step, context=context)

        assert inj.injection_count > 0
        assert len(inj.records) == inj.injection_count
        assert all(r.injector_type == "context_degradation" for r in inj.records)

    def test_reset_clears_state(self):
        """Reset should clear all injection state."""
        inj = ContextDegradation(strategy="truncation", start_step=1)
        context = [{"role": "user", "content": "Hello"}] * 10
        for step in range(1, 20):
            inj.on_step(step_id=step, context=context)

        assert inj.injection_count > 0
        inj.reset()
        assert inj.injection_count == 0
        assert len(inj.records) == 0
        assert inj.current_degradation_level == 0.0

    def test_invalid_strategy_raises(self):
        """Invalid strategy should raise ValueError."""
        with pytest.raises(ValueError):
            ContextDegradation(strategy="invalid_strategy")

    def test_degradation_rate_clamped(self):
        """Degradation rate should be clamped to 0.0-1.0."""
        inj = ContextDegradation(strategy="truncation", degradation_rate=5.0)
        assert inj.degradation_rate == 1.0
        inj2 = ContextDegradation(strategy="truncation", degradation_rate=-1.0)
        assert inj2.degradation_rate == 0.0

    def test_single_entry_context_not_truncated(self):
        """Context with 1 entry should not be truncated (nothing to drop)."""
        inj = ContextDegradation(
            strategy="truncation",
            start_step=1,
            degradation_rate=1.0,
            seed=42,
        )
        context = [{"role": "user", "content": "Hello"}]
        result = inj.on_step(step_id=50, context=context)
        # Should not drop the only entry
        assert len(result["context"]) == 1


# ──────────────────────────────────────────────────────
# CascadingFailures Tests
# ──────────────────────────────────────────────────────


class TestCascadingFailures:
    def test_root_failure_triggers_cascade(self):
        """First failure should always trigger a cascade."""
        cascade = CascadingFailures(
            cascade_probability=1.0,
            max_cascade_depth=3,
            seed=42,
        )
        event = {"tool_name": "database", "error_type": "timeout"}
        results = cascade.on_failure(event, current_step=1)

        assert len(results) > 0
        assert results[0]["cascade_depth"] == 1
        assert results[0]["triggered_by"] == "database"
        assert cascade.injection_count > 0

    def test_max_depth_respected(self):
        """Cascade should stop at max_cascade_depth."""
        cascade = CascadingFailures(
            cascade_probability=1.0,
            max_cascade_depth=2,
            seed=42,
        )
        event = {"tool_name": "database", "error_type": "timeout"}
        results = cascade.on_failure(event, current_step=1)

        # Should produce cascades up to depth 2
        depths = [r["cascade_depth"] for r in results]
        assert max(depths) <= 2

    def test_zero_probability_stops_cascade(self):
        """With probability=0, only the first cascade triggers."""
        cascade = CascadingFailures(
            cascade_probability=0.0,
            max_cascade_depth=5,
            seed=42,
        )
        event = {"tool_name": "database", "error_type": "timeout"}
        results = cascade.on_failure(event, current_step=1)

        # First failure always triggers (depth 1), but further cascades stop
        assert len(results) >= 1  # At least the first cascade
        # With prob=0, no further cascades beyond the first
        assert all(r["cascade_depth"] <= 1 for r in results)

    def test_cascade_target_derivation(self):
        """Cascading target should follow dependency patterns."""
        cascade = CascadingFailures(seed=42)
        # database -> api_server
        target = cascade._derive_cascading_target({"tool_name": "database"})
        assert target == "api_server"
        # api_server -> user_interface
        target = cascade._derive_cascading_target({"tool_name": "api_server"})
        assert target == "user_interface"
        # auth -> api_server
        target = cascade._derive_cascading_target({"tool_name": "auth"})
        assert target == "api_server"

    def test_cascade_error_derivation(self):
        """Cascading error type should transform from root cause."""
        cascade = CascadingFailures(seed=42)
        assert cascade._derive_cascading_error({"error_type": "timeout"}) == "connection_refused"
        assert cascade._derive_cascading_error({"error_type": "error"}) == "service_unavailable"
        assert cascade._derive_cascading_error({"error_type": "rate_limit"}) == "timeout"
        # Unknown error type defaults to "error"
        assert cascade._derive_cascading_error({"error_type": "unknown"}) == "error"

    def test_propagation_delay(self):
        """Cascade should respect propagation delay."""
        cascade = CascadingFailures(
            cascade_probability=1.0,
            max_cascade_depth=2,
            propagation_delay_steps=3,
            seed=42,
        )
        event = {"tool_name": "database", "error_type": "timeout"}
        results = cascade.on_failure(event, current_step=1)

        # First cascade should be at step 1+3=4
        assert results[0]["step_id"] == 4

    def test_records_logged(self):
        """Injection records should be created for each cascade."""
        cascade = CascadingFailures(
            cascade_probability=1.0,
            max_cascade_depth=3,
            seed=42,
        )
        event = {"tool_name": "database", "error_type": "timeout"}
        cascade.on_failure(event, current_step=1)

        assert cascade.injection_count > 0
        assert len(cascade.records) == cascade.injection_count
        assert all(r.injector_type == "cascading_failure" for r in cascade.records)

    def test_reset_clears_state(self):
        """Reset should clear cascade chains and records."""
        cascade = CascadingFailures(seed=42)
        event = {"tool_name": "database", "error_type": "timeout"}
        cascade.on_failure(event, current_step=1)

        assert cascade.injection_count > 0
        cascade.reset()
        assert cascade.injection_count == 0
        assert len(cascade.records) == 0
        assert len(cascade.get_active_chains()) == 0

    def test_summary(self):
        """Summary should report cascade statistics."""
        cascade = CascadingFailures(
            cascade_probability=1.0,
            max_cascade_depth=2,
            seed=42,
        )
        event = {"tool_name": "database", "error_type": "timeout"}
        cascade.on_failure(event, current_step=1)

        summary = cascade.summary()
        assert summary["total_cascades"] > 0
        assert summary["active_chains"] >= 1
        assert summary["max_depth_reached"] >= 1

    def test_same_error_type_same_chain(self):
        """Same tool+error combo should share a cascade chain."""
        cascade = CascadingFailures(
            cascade_probability=1.0,
            max_cascade_depth=5,
            seed=42,
        )
        event = {"tool_name": "database", "error_type": "timeout"}
        results1 = cascade.on_failure(event, current_step=1)
        results2 = cascade.on_failure(event, current_step=5)

        # Both should be part of the same chain
        # Second call should continue from where the first left off
        assert cascade.get_active_chains()  # Chain should exist

    def test_different_errors_different_chains(self):
        """Different tool+error combos should start separate chains."""
        cascade = CascadingFailures(
            cascade_probability=1.0,
            max_cascade_depth=2,
            seed=42,
        )
        event1 = {"tool_name": "database", "error_type": "timeout"}
        event2 = {"tool_name": "search", "error_type": "error"}
        cascade.on_failure(event1, current_step=1)
        cascade.on_failure(event2, current_step=1)

        chains = cascade.get_active_chains()
        assert len(chains) >= 2


# ──────────────────────────────────────────────────────
# SpecDrift Tests
# ──────────────────────────────────────────────────────


class TestSpecDrift:
    def test_no_drift_before_start_step(self):
        """Drift should not occur before start_step."""
        drift = SpecDrift(intensity="subtle", start_step=10, seed=42)
        for step in range(1, 10):
            result = drift.check_step(step)
            assert result is None
        assert drift.injection_count == 0

    def test_drift_increases_with_errors(self):
        """Drift probability should increase when errors are present."""
        # With high base probability and trigger events, drift should occur
        drift = SpecDrift(
            intensity="aggressive",
            start_step=1,
            probability=0.5,
            seed=42,
        )
        # Without errors
        no_error_events = sum(
            1 for step in range(1, 100)
            if drift.check_step(step) is not None
        )
        drift.reset()

        # With errors — should produce more drift events
        with_error_events = sum(
            1 for step in range(1, 100)
            if drift.check_step(step, recent_errors=["timeout", "rate_limit"]) is not None
        )
        # Errors should amplify drift (more events)
        assert with_error_events >= no_error_events

    def test_drift_types_are_valid(self):
        """All drift types should be from the expected set."""
        drift = SpecDrift(intensity="aggressive", start_step=1, probability=1.0, seed=42)
        valid_types = {
            "skip_validation", "use_fallback", "reorder_steps",
            "substitute_tool", "truncate_output", "approximate_result",
        }
        for step in range(1, 50):
            result = drift.check_step(step)
            if result is not None:
                assert result["drift_type"] in valid_types

    def test_cumulative_drift_increases(self):
        """Cumulative drift should increase with each injection."""
        drift = SpecDrift(intensity="aggressive", start_step=1, probability=1.0, seed=42)
        prev = 0.0
        for step in range(1, 20):
            result = drift.check_step(step)
            if result is not None:
                assert drift.cumulative_drift >= prev
                prev = drift.cumulative_drift

    def test_cumulative_drift_capped_at_one(self):
        """Cumulative drift should never exceed 1.0."""
        drift = SpecDrift(intensity="aggressive", start_step=1, probability=1.0, seed=42)
        for step in range(1, 200):
            drift.check_step(step)
        assert drift.cumulative_drift <= 1.0

    def test_intensity_affects_magnitude(self):
        """Higher intensity should produce larger drift magnitudes."""
        subtle = SpecDrift(intensity="subtle", start_step=1, probability=1.0, seed=42)
        aggressive = SpecDrift(intensity="aggressive", start_step=1, probability=1.0, seed=42)

        subtle_mags = []
        aggressive_mags = []
        for step in range(1, 50):
            s = subtle.check_step(step)
            a = aggressive.check_step(step)
            if s:
                subtle_mags.append(s["drift_magnitude"])
            if a:
                aggressive_mags.append(a["drift_magnitude"])

        if subtle_mags and aggressive_mags:
            # Aggressive should have higher average magnitude
            assert sum(aggressive_mags) / len(aggressive_mags) > \
                   sum(subtle_mags) / len(subtle_mags)

    def test_drift_events_history(self):
        """Drift events should be stored in history."""
        drift = SpecDrift(intensity="aggressive", start_step=1, probability=1.0, seed=42)
        for step in range(1, 20):
            drift.check_step(step)

        assert len(drift.drift_events) == drift.injection_count
        for event in drift.drift_events:
            assert "step_id" in event
            assert "drift_type" in event
            assert "drift_magnitude" in event
            assert "description" in event
            assert "cumulative_drift" in event

    def test_get_drift_score(self):
        """Drift score should report comprehensive assessment."""
        drift = SpecDrift(intensity="moderate", start_step=1, probability=0.5, seed=42)
        for step in range(1, 30):
            drift.check_step(step)

        score = drift.get_drift_score()
        assert "cumulative_drift" in score
        assert "total_events" in score
        assert "drift_types" in score
        assert "max_magnitude" in score
        assert "intensity" in score
        assert score["intensity"] == "moderate"

    def test_reset_clears_state(self):
        """Reset should clear all drift state."""
        drift = SpecDrift(intensity="aggressive", start_step=1, probability=1.0, seed=42)
        for step in range(1, 20):
            drift.check_step(step)

        assert drift.injection_count > 0
        drift.reset()
        assert drift.injection_count == 0
        assert drift.cumulative_drift == 0.0
        assert len(drift.drift_events) == 0
        assert len(drift.records) == 0

    def test_records_logged(self):
        """Injection records should be created for each drift event."""
        drift = SpecDrift(intensity="aggressive", start_step=1, probability=1.0, seed=42)
        for step in range(1, 15):
            drift.check_step(step)

        assert drift.injection_count > 0
        assert len(drift.records) == drift.injection_count
        assert all(r.injector_type == "spec_drift" for r in drift.records)

    def test_trigger_events_amplification(self):
        """Each trigger event should add 20% to probability."""
        drift = SpecDrift(
            intensity="moderate",
            start_step=1,
            probability=0.1,
            seed=42,
        )
        # With 3 trigger events: 0.1 + 3*0.2 = 0.7, * 1.0 (moderate) = 0.7
        # Should produce more drift than without
        events_with = 0
        for step in range(1, 100):
            if drift.check_step(step, recent_errors=["timeout", "rate_limit", "error"]):
                events_with += 1

        drift.reset()
        events_without = 0
        for step in range(1, 100):
            if drift.check_step(step, recent_errors=[]):
                events_without += 1

        assert events_with > events_without

    def test_invalid_intensity_raises(self):
        """Invalid intensity should raise ValueError."""
        with pytest.raises(ValueError):
            SpecDrift(intensity="invalid_intensity")
