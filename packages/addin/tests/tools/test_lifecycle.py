"""Lifecycle tool tests against the behavioral fake: fusion_status and
list_documents, including the no-document cold-start path."""

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)
from fake_fusion import values
from fake_fusion.documents import FakeDataFile


def test_fusion_status_reports_active_design(fusion, call, mcp):
    payload = mcp.ok(call("fusion_status"))
    assert payload["document_name"] == "Test Design"
    assert payload["design_type"] == "parametric"
    assert payload["units"] == "cm"
    assert payload["workspace"] == "Design"
    assert payload["timeline_feature_count"] == 0
    assert payload["fusion_version"]


def test_fusion_status_works_with_no_document(fusion_empty, call, mcp):
    payload = mcp.ok(call("fusion_status"))
    assert payload["document_name"] is None
    assert payload["is_modified"] is None
    assert payload["design_type"] is None
    assert payload["timeline_feature_count"] is None
    # Uptime is always a number, even before any document exists.
    assert isinstance(payload["addin_uptime_s"], float)


def test_fusion_status_tracks_modification(fusion, call, mcp):
    fusion.document.isModified = True
    payload = mcp.ok(call("fusion_status"))
    assert payload["is_modified"] is True


def test_fusion_status_reports_direct_design_without_timeline(fusion, call, mcp):
    fusion.design.designType = values.DesignTypes.DirectDesignType
    payload = mcp.ok(call("fusion_status"))
    assert payload["design_type"] == "direct"
    # Direct modeling has no timeline at all.
    assert payload["timeline_feature_count"] is None


def test_list_documents_reports_every_open_document(fusion, call, mcp):
    fusion.new_document("Second")
    payload = mcp.ok(call("list_documents"))
    assert payload["count"] == 2
    names = {entry["name"] for entry in payload["documents"]}
    assert names == {"Test Design", "Second"}


def test_list_documents_marks_active_and_saved_path(fusion, call, mcp):
    fusion.document.dataFile = FakeDataFile("/tmp/box.f3d")
    entry = next(e for e in mcp.ok(call("list_documents"))["documents"] if e["is_active"])
    assert entry["saved_path"] == "/tmp/box.f3d"
    assert entry["design_type"] == "parametric"


def test_list_documents_empty_when_nothing_open(fusion_empty, call, mcp):
    payload = mcp.ok(call("list_documents"))
    assert payload == {"count": 0, "documents": []}
