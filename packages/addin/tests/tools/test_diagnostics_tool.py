"""Diagnostics tool tests: the snapshot is served verbatim, anywhere.

``fusion_diagnostics`` is deliberately the one tool that never reports failure
-- its whole purpose is to answer "is this add-in alive, and how is it doing?"
A client may call it before the dispatch loop is up, before any document is
open, or in the middle of a failing burst, and it must still return the
snapshot rather than an error envelope.  That is why the handler wraps
``diagnostics.snapshot()`` with no ``map_tool_errors`` and no ``adsk`` reach.
"""

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)

from fusion_bridge import diagnostics


def test_serves_the_snapshot_verbatim(fusion, call, mcp):
    # The tool is a thin reader: whatever the module reports is what the client
    # gets, with no reshaping or filtering added on the way out.
    diagnostics.reset()
    diagnostics.record_call()
    diagnostics.record_error("internal")
    payload = mcp.ok(call("fusion_diagnostics"))
    snapshot = diagnostics.snapshot()
    assert payload == snapshot
    assert payload["tool_calls"] == 1
    assert payload["tool_errors"] == 1
    assert payload["error_kinds"]["internal"] == 1


def test_reports_the_live_tool_inventory_including_itself(fusion, call, mcp):
    payload = mcp.ok(call("fusion_diagnostics"))
    # The tool names come from the handler registry, which already carries this
    # tool, so the inventory reports one more than the pre-diagnostics surface.
    assert "fusion_diagnostics" in payload["tool_names"]
    assert payload["tool_count"] == len(payload["tool_names"])
    assert payload["tool_count"] >= 19


def test_is_safe_before_any_document_is_open(fusion_empty, call, mcp):
    # Cold start: no dispatch state, no document. Still a snapshot, never an error.
    payload = mcp.ok(call("fusion_diagnostics"))
    assert isinstance(payload["ready"], bool)
    assert payload["document_open"] is False
    assert set(payload) == set(diagnostics.SNAPSHOT_FIELDS)


def test_accumulates_counts_seen_by_a_later_call(fusion, call, mcp):
    # Counting happens in the MCP dispatch layer (runtime.py), not inside the
    # handler, so the ``call`` fixture does not by itself move these numbers.
    # What the tool must guarantee is that whatever the counters saw, a later
    # call reports -- including counts the tool itself did not cause.
    diagnostics.reset()
    diagnostics.record_call()
    diagnostics.record_error("network_failure")
    payload = mcp.ok(call("fusion_diagnostics"))
    assert payload["tool_calls"] == 1
    assert payload["tool_errors"] == 1
    assert payload["error_kinds"]["network_failure"] == 1
