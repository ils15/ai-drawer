"""Read-only diagnostics tools: readiness flags and cumulative counters."""

from .. import diagnostics
from ..value_builders import success_result


def snapshot(arguments):
    """Return the diagnostics snapshot: readiness, tool inventory, error counts.

    Takes no arguments and never fails into an error envelope: the snapshot is
    best-effort, so a client may call it before anything else is up to decide
    whether this add-in is the thing that is not answering.
    """
    del arguments
    return success_result(diagnostics.snapshot())
