"""Tests for Phase 6 advanced chaos injectors.

Tests NetworkPartition, ClockSkew, MemoryPressure, and chaos presets.
"""

import time

from sentinel.chaos import (
    ClockSkew,
    MemoryPressure,
    MockToolError,
    NetworkPartition,
)
from sentinel.env import MockTool

# ─── NetworkPartition ──────────────────────────────────────────

class TestNetworkPartition:
    """Test network partition simulation."""

    def test_reachable_service(self):
        """Service in connectivity list is reachable."""
        partition = NetworkPartition(
            connectivity={"api": ["db", "cache"], "db": ["api"]},
        )
        assert partition.is_reachable("api", "db")
        assert partition.is_reachable("api", "cache")
        assert partition.is_reachable("db", "api")

    def test_unreachable_service(self):
        """Service not in connectivity list is unreachable."""
        partition = NetworkPartition(
            connectivity={"api": ["db"], "db": ["api"]},
        )
        assert not partition.is_reachable("api", "cache")
        assert not partition.is_reachable("cache", "api")

    def test_empty_connectivity(self):
        """Empty connectivity means nothing is reachable."""
        partition = NetworkPartition(
            connectivity={"api": [], "db": []},
        )
        assert not partition.is_reachable("api", "db")

    def test_partition_always_active(self):
        """With probability=1.0, partition always injects."""
        partition = NetworkPartition(
            connectivity={"api": []},  # api cannot reach anything
            partition_probability=1.0,
        )
        # api has no connections, so partition should inject
        assert partition._should_inject()

    def test_partition_heals(self):
        """Partition heals after heal_after_calls."""
        partition = NetworkPartition(
            connectivity={"api": []},
            partition_probability=1.0,
            heal_after_calls=3,
        )
        # First 3 calls are blocked
        for _ in range(3):
            result = partition._should_inject()
            assert result, "Call should inject before healing"
        # After healing, no more blocks
        assert not partition._should_inject()
        assert not partition._partition_active

    def test_reset(self):
        """Reset restores initial state."""
        partition = NetworkPartition(
            connectivity={"api": []},
            partition_probability=1.0,
            heal_after_calls=2,
        )
        partition._should_inject()
        partition._should_inject()
        # Heal check happens at start of next call
        partition._should_inject()
        assert not partition._partition_active

        partition.reset()
        assert partition._partition_active
        assert partition._injection_count == 0
        assert partition._call_count == 0

    def test_wrap_tool(self):
        """wrap() returns a ChaosToolWrapper."""
        partition = NetworkPartition(
            connectivity={"api": []},
            partition_probability=1.0,
        )
        mock = MockTool("api", response="ok")
        wrapper = partition.wrap(mock)
        assert wrapper.name == "api"

    def test_make_validator(self):
        """make_validator returns a callable."""
        partition = NetworkPartition(connectivity={})
        validator = partition.make_validator()
        assert callable(validator)
        assert validator("some output")


# ─── ClockSkew ─────────────────────────────────────────────────

class TestClockSkew:
    """Test clock skew simulation."""

    def test_basic_skew(self):
        """Clock skew shifts timestamps."""
        skew = ClockSkew(skew_seconds=300)
        ts = skew.get_skewed_timestamp()
        expected = time.time() + 300
        assert abs(ts - expected) < 1.0

    def test_negative_skew(self):
        """Negative skew means agent clock is behind."""
        skew = ClockSkew(skew_seconds=-300)
        ts = skew.get_skewed_timestamp()
        expected = time.time() - 300
        assert abs(ts - expected) < 1.0

    def test_drift_rate(self):
        """Drift rate increases skew over time."""
        skew = ClockSkew(skew_seconds=0, drift_rate=10)
        skew._should_inject()  # call 1
        assert skew.current_skew == 10
        skew._should_inject()  # call 2
        assert skew.current_skew == 20

    def test_affected_tools(self):
        """Only affected tools get skewed timestamps."""
        skew = ClockSkew(
            skew_seconds=300,
            affected_tools=["auth"],
        )
        ts_auth = skew.get_skewed_timestamp(tool_name="auth")
        ts_api = skew.get_skewed_timestamp(tool_name="api")
        # Auth should be skewed, api should not
        assert abs(ts_auth - (time.time() + 300)) < 1.0
        assert abs(ts_api - time.time()) < 1.0

    def test_creates_auth_error(self):
        """Clock skew creates authentication errors."""
        skew = ClockSkew(skew_seconds=300)
        error = skew._create_failure({})
        assert isinstance(error, MockToolError)
        assert "401" in str(error.status_code) or "skew" in str(error).lower()

    def test_reset(self):
        """Reset restores initial skew."""
        skew = ClockSkew(skew_seconds=100, drift_rate=10)
        skew._should_inject()
        skew._should_inject()
        assert skew.current_skew == 120

        skew.reset()
        assert skew.current_skew == 100
        assert skew._call_count == 0

    def test_make_validator(self):
        """make_validator returns a callable."""
        skew = ClockSkew()
        validator = skew.make_validator()
        assert callable(validator)
        assert validator("output")


# ─── MemoryPressure ────────────────────────────────────────────

class TestMemoryPressure:
    """Test memory pressure simulation."""

    def test_under_limit(self):
        """No issues when under limit."""
        pressure = MemoryPressure(max_context_tokens=1000)
        result = pressure.simulate_token_usage(500)
        assert result is None
        assert pressure.current_usage == 500

    def test_over_limit_triggers_eviction(self):
        """Over limit triggers eviction."""
        pressure = MemoryPressure(
            max_context_tokens=1000,
            eviction_strategy="fifo",
        )
        pressure.simulate_token_usage(900)
        result = pressure.simulate_token_usage(200)  # 1100 > 1000
        assert result is not None
        assert "eviction" in result.lower()
        assert pressure.current_usage <= 1000

    def test_oom_kill(self):
        """OOM kill resets context."""
        pressure = MemoryPressure(
            max_context_tokens=100,
            oom_probability=1.0,  # Always OOM
        )
        pressure.simulate_token_usage(50)
        result = pressure.simulate_token_usage(60)  # 110 > 100
        assert result is not None
        assert "oom" in result.lower()
        assert pressure.current_usage == 0  # Reset after OOM

    def test_usage_percentage(self):
        """Usage percentage calculates correctly."""
        pressure = MemoryPressure(max_context_tokens=1000)
        pressure.simulate_token_usage(300)
        assert pressure.usage_percentage == 0.3

    def test_under_pressure(self):
        """under_pressure returns True above threshold."""
        pressure = MemoryPressure(
            max_context_tokens=1000,
            pressure_threshold=0.8,
        )
        pressure.simulate_token_usage(700)
        assert not pressure.under_pressure
        pressure.simulate_token_usage(100)
        assert pressure.under_pressure

    def test_eviction_strategies(self):
        """All eviction strategies work."""
        for strategy in ["fifo", "priority", "random"]:
            pressure = MemoryPressure(
                max_context_tokens=1000,
                eviction_strategy=strategy,
            )
            pressure.simulate_token_usage(900)
            result = pressure.simulate_token_usage(200)
            assert result is not None
            assert pressure.current_usage <= 1000

    def test_reset(self):
        """Reset clears all state."""
        pressure = MemoryPressure(max_context_tokens=1000)
        pressure.simulate_token_usage(500)
        pressure.reset()
        assert pressure.current_usage == 0
        assert pressure._call_count == 0

    def test_make_validator(self):
        """make_validator returns a callable."""
        pressure = MemoryPressure()
        validator = pressure.make_validator()
        assert callable(validator)
        assert validator("output")


# ─── Chaos Presets ─────────────────────────────────────────────

class TestChaosPresets:
    """Test that presets are importable and correctly structured."""

    def test_import_presets(self):
        """All presets can be imported."""
        from sentinel.chaos_presets import (
            PRESETS,
        )
        assert len(PRESETS) == 7

    def test_presets_are_lists(self):
        """All presets are lists of injectors."""
        from sentinel.chaos_presets import PRESETS
        for name, preset in PRESETS.items():
            assert isinstance(preset, list), f"{name} is not a list"
            assert len(preset) > 0, f"{name} is empty"

    def test_production_incident_structure(self):
        """Production incident has expected injectors."""
        from sentinel.chaos_presets import PRODUCTION_INCIDENT
        types = [type(p).__name__ for p in PRODUCTION_INCIDENT]
        assert "ToolFailureInjector" in types
        assert "ContextDegradation" in types

    def test_network_partition_preset(self):
        """Network partition preset has NetworkPartition."""
        from sentinel.chaos_presets import NETWORK_PARTITION
        types = [type(p).__name__ for p in NETWORK_PARTITION]
        assert "NetworkPartition" in types

    def test_time_travel_preset(self):
        """Time travel preset has ClockSkew."""
        from sentinel.chaos_presets import TIME_TRAVEL
        types = [type(p).__name__ for p in TIME_TRAVEL]
        assert "ClockSkew" in types

    def test_memory_leak_preset(self):
        """Memory leak preset has MemoryPressure."""
        from sentinel.chaos_presets import MEMORY_LEAK
        types = [type(p).__name__ for p in MEMORY_LEAK]
        assert "MemoryPressure" in types

    def test_preset_wraps_mock(self):
        """Preset injectors can wrap mock tools."""
        from sentinel.chaos_presets import PRODUCTION_INCIDENT
        mock = MockTool("database", response="ok")
        for injector in PRODUCTION_INCIDENT:
            if hasattr(injector, 'wrap'):
                wrapper = injector.wrap(mock)
                assert wrapper is not None
