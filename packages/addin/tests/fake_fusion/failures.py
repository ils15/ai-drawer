"""Failure injection for the behavioral Fusion fake.

A test queues a simulated Fusion failure with ``fusion.fail_next(kind)``; the
next matching fake call then raises or returns ``None`` exactly once.  That
makes a tool's error branch reachable offline, without monkeypatching SDK
methods and without touching the tool code.

Nothing here is automatic.  Injection only happens for a kind that was
explicitly queued, each queued kind fires once and then clears itself, and the
injector lives on the per-test ``FakeFusion`` instance the ``fusion`` fixture
builds -- so it is never shared with a test that did not ask for it.
"""

from __future__ import annotations

# Kinds the fake can simulate, named for the tool error they surface:
# duplicate add -> parameter_already_exists, a missed lookup ->
# parameter_not_found, a rejected expression -> invalid_expression, a build
# without the PDF creator -> unsupported_operation, an unreadable file ->
# not_found.
INJECTABLE_KINDS = (
    "duplicate_parameter",
    "unknown_parameter",
    "invalid_expression",
    "no_pdf_export",
    "open_returns_none",
)

_INJECTABLE = frozenset(INJECTABLE_KINDS)


class FailureInjector:
    """Queued one-shot failures for a single fake Fusion instance."""

    def __init__(self):
        self._pending: set[str] = set()

    def fail_next(self, kind):
        """Queue *kind* to fire on the next matching fake call."""
        if kind not in _INJECTABLE:
            raise ValueError(
                f"unknown failure kind {kind!r}; expected one of "
                f"{', '.join(INJECTABLE_KINDS)}"
            )
        self._pending.add(kind)

    def fire(self, kind):
        """Consume one queued *kind*; ``True`` exactly once per ``fail_next``."""
        if kind in self._pending:
            self._pending.discard(kind)
            return True
        return False

    def queued(self, kind):
        """Whether *kind* is queued (without consuming it)."""
        return kind in self._pending

    def clear(self):
        """Drop every queued failure."""
        self._pending.clear()
