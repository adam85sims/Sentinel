"""Stream service — in-memory pub/sub for SSE event broadcasting.

Provides a simple per-run event queue so that multiple SSE clients
can subscribe to real-time progress updates for a scenario run.

Design notes:
- Each run gets its own ``asyncio.Queue`` keyed by run_id.
- ``publish()`` is non-blocking (uses ``put_nowait``); callers
  should handle ``QueueFull`` gracefully.
- ``get_events()`` is an async generator that yields SSE-formatted
  strings, suitable for ``EventSourceResponse``.
- Queues are unbounded; the ``stream_service`` does NOT own the
  run lifecycle — ``run_manager`` is responsible for cleanup.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StreamEvent:
    """A single event to be broadcast over SSE.

    ``event_type`` maps to the SSE ``event:`` field.
    ``data`` is JSON-serialised and sent as the SSE ``data:`` field.
    """

    event_type: str  # e.g. "started", "progress", "completed", "error"
    data: dict[str, Any] = field(default_factory=dict)


# In-memory pub/sub — one queue per run_id.
# Queues are created on demand by register_run() and removed by
# unregister_run().  get_events() reads until it sees a sentinel
# value (None) or the client disconnects.
_queues: dict[str, asyncio.Queue] = {}

# Sentinel value pushed when a run completes to signal the SSE
# generator to stop yielding.
_SENTINEL = None


def register_run(run_id: str) -> None:
    """Create a new event queue for a run.

    Idempotent — calling twice with the same run_id replaces the
    old queue (which would be stale after a restart).
    """
    _queues[run_id] = asyncio.Queue()


def unregister_run(run_id: str) -> None:
    """Remove the event queue for a completed run.

    Safe to call even if the run_id doesn't exist (no-op).
    """
    _queues.pop(run_id, None)


def publish(run_id: str, event: StreamEvent) -> None:
    """Publish an event to all SSE subscribers of a run.

    Uses ``put_nowait`` to avoid blocking the caller. If the queue
    is full (slow consumer), the event is silently dropped — this
    is acceptable for a dev dashboard where missing a progress
    update is non-critical.
    """
    queue = _queues.get(run_id)
    if queue is None:
        return

    payload = {
        "event": event.event_type,
        "data": json.dumps(event.data, default=str),
    }
    try:
        queue.put_nowait(payload)
    except asyncio.QueueFull:
        pass


def publish_run_event(run_id: str, event_type: str, data: dict[str, Any]) -> None:
    """Convenience wrapper — creates a StreamEvent and publishes it."""
    publish(run_id, StreamEvent(event_type=event_type, data=data))


async def get_events(run_id: str) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE-formatted event strings.

    Each yield produces a string in the format::

        event: <event_type>
        data: <json>

    The generator runs until the queue receives ``None`` (sentinel)
    or the client disconnects.  The queue is left in place so
    reconnecting clients can pick up new events (though they'll
    miss anything already consumed — acceptable for live streaming).
    """
    queue = _queues.get(run_id)
    if queue is None:
        return

    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            # ``item`` is already a dict with 'event' and 'data' keys
            # formatted as SSE-compatible strings.
            yield f"event: {item['event']}\ndata: {item['data']}\n\n"
    except asyncio.CancelledError:
        pass
