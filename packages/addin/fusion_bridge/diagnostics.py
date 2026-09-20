"""Thread-safe runtime diagnostics: counters and readiness, nothing else.

The add-in is a long-running process inside Fusion, so when a client reports
"a tool failed", the question that follows is always "how many, and which
kind?".  This module answers that without becoming a leak surface: it counts
tool calls and errors per :data:`~fusion_bridge.errors.ERROR_KINDS`, and can
report readiness plus the live tool inventory.

What it deliberately does *not* do is collect messages, exception text, file
paths, environment, script names, or ``adsk`` objects.  Those are the things
a diagnostics endpoint must never hand to an LLM client.  The whitelist in
:data:`SNAPSHOT_FIELDS` is the entire contract: anything not listed here does
not exist in a snapshot, so a future contributor cannot add a leak by
forgetting to filter.
"""

import threading

from .errors import ERROR_KINDS

# The only fields a snapshot may contain.  ``error_kinds`` is a per-kind count
# dict; ``tool_names`` is a list of tool *names* only.
SNAPSHOT_FIELDS = (
    "ready",
    "dispatch_active",
    "document_open",
    "tool_count",
    "tool_names",
    "tool_calls",
    "tool_errors",
    "error_kinds",
)

# Main-thread dispatch serves up to this many concurrent client slots; the
# lock only guards counter writes, and is held for a few instructions, so a
# single lock is enough well beyond it.
_LOCK = threading.Lock()

_tool_calls = 0
_tool_errors = 0
_error_kinds = {kind: 0 for kind in ERROR_KINDS}


def record_call():
    """Count one completed tool call (success or failure)."""
    global _tool_calls
    with _LOCK:
        _tool_calls += 1


def record_error(kind=None):
    """Count one tool failure, optionally attributing it to *kind*.

    An unrecognized or missing kind still increments the error total -- a
    failure we cannot classify is still a failure -- but never adds a key to
    the per-kind dict, so the taxonomy in the snapshot stays closed.
    """
    global _tool_errors
    with _LOCK:
        _tool_errors += 1
        if kind in _error_kinds:
            _error_kinds[kind] += 1


def reset():
    """Zero every counter.  Tests use this to isolate diagnostics state."""
    global _tool_calls, _tool_errors
    with _LOCK:
        _tool_calls = 0
        _tool_errors = 0
        for kind in _error_kinds:
            _error_kinds[kind] = 0


def _readiness():
    """Best-effort readiness flags; never raises into a tool result."""
    flags = {"dispatch_active": False, "document_open": False, "ready": False}
    try:
        from . import dispatch

        flags["dispatch_active"] = bool(
            getattr(dispatch, "_scheduler_active", None)
            and dispatch._scheduler_active.is_set()
        )
    except Exception:
        pass
    try:
        from . import runtime

        flags["ready"] = flags["dispatch_active"] and bool(
            getattr(runtime, "_server", None)
        )
    except Exception:
        pass
    try:
        import adsk.core

        app = adsk.core.Application.get()
        flags["document_open"] = bool(app is not None and app.activeDocument is not None)
    except Exception:
        pass
    return flags


def _live_tool_names():
    """Names of the tools currently wired into the handler registry."""
    try:
        from . import operations

        return sorted(operations.TOOL_HANDLERS)
    except Exception:
        return []


def snapshot():
    """Return the whitelisted diagnostics payload.

    The result is JSON-serializable and contains only counts, flags, and tool
    names.  Callers may hand it to a client without filtering.
    """
    with _LOCK:
        tool_calls = _tool_calls
        tool_errors = _tool_errors
        error_kinds = dict(_error_kinds)
    flags = _readiness()
    tool_names = _live_tool_names()
    return {
        "ready": flags["ready"],
        "dispatch_active": flags["dispatch_active"],
        "document_open": flags["document_open"],
        "tool_count": len(tool_names),
        "tool_names": tool_names,
        "tool_calls": tool_calls,
        "tool_errors": tool_errors,
        "error_kinds": error_kinds,
    }
