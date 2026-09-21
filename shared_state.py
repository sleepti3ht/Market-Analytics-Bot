"""Shared runtime state shared between WebSocket listener and Telegram bot.

WebSocket writes the latest event latency (ms), Telegram bot reads it to show
in /status. Kept in a tiny module with a global so both sides can access it
without heavy DB/profiling logic.
"""
import time

# Timestamp (monotonic) of the last WebSocket event received on-channel
_last_event_time: float = 0.0
# Last measured delay between two consecutive events, in milliseconds
_last_latency_ms: float = 0.0
# Timestamp (unix) when the last latency was measured (for "updated at")
_last_latency_at: float = 0.0


def record_event() -> None:
    """Call this each time a WebSocket event is received.

    Measures the gap between this event and the previous one and stores it
    as the current latency. Beware: this is the *arrival gap* on our side,
    not a round-trip latency to the server.
    """
    global _last_event_time, _last_latency_ms, _last_latency_at
    now = time.monotonic()
    if _last_event_time:
        _last_latency_ms = (now - _last_event_time) * 1000.0
        _last_latency_at = time.time()
    _last_event_time = now


def get_latest_latency_ms() -> float:
    """Returns the most recent measured latency in ms (0.0 if none yet)."""
    return _last_latency_ms


def get_last_latency_time() -> float:
    """Unix timestamp of the last latency measurement (0.0 if never)."""
    return _last_latency_at


def reset() -> None:
    """Clear counters (e.g. after reconnection)."""
    global _last_event_time, _last_latency_ms, _last_latency_at
    _last_event_time = 0.0
    _last_latency_ms = 0.0
    _last_latency_at = 0.0