"""Document tool tests against the behavioral fake: create, open, save,
export, close, and get_document_info -- happy paths plus the semantic failures
that a mock agreeing with a wrong assumption would hide."""

import os

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)


def test_new_document_creates_and_activates(fusion, call, mcp):
    payload = mcp.ok(call("new_document", name="Bracket"))
    assert payload == {"document_name": "Bracket", "design_type": "parametric"}
    assert fusion.document.name == "Bracket"
    assert fusion.design is not None


def test_new_document_requires_a_name(fusion, call, mcp):
    assert "missing required argument" in mcp.error(call("new_document"))


def test_new_document_rejects_unknown_design_type(fusion, call, mcp):
    message = mcp.error(call("new_document", name="X", design_type="imaginary"))
    assert "design_type must be one of" in message


def test_new_document_direct_switches_the_design(fusion, call, mcp):
    payload = mcp.ok(call("new_document", name="Direct", design_type="direct"))
    assert payload["design_type"] == "direct"
    assert fusion.design.designType is not None
    assert fusion.design.timeline is None


def test_open_document_opens_a_real_file(fusion, tmp_path, call, mcp):
    path = tmp_path / "part.f3d"
    path.write_bytes(b"FAKE F3D")
    payload = mcp.ok(call("open_document", path=str(path)))
    assert payload["document_name"] == "part.f3d"
    assert payload["is_modified"] is False
    assert fusion.document.dataFile.path == str(path)


def test_open_document_rejects_missing_file(fusion, tmp_path, call, mcp):
    missing = tmp_path / "nope.f3d"
    message = mcp.error(call("open_document", path=str(missing)))
    assert "could not open" in message


def test_save_document_in_place_after_a_save_as(fusion, tmp_path, call, mcp):
    target = tmp_path / "saved.f3d"
    mcp.ok(call("save_document", path=str(target)))
    fusion.document.isModified = True
    payload = mcp.ok(call("save_document"))
    assert payload["saved_path"] == str(target)
    assert fusion.document.isModified is False


def test_save_document_without_path_requires_a_save_location(fusion, call, mcp):
    message = mcp.error(call("save_document"))
    assert "never been saved" in message


def test_save_document_save_as_writes_through(fusion, tmp_path, call, mcp):
    target = tmp_path / "as.f3d"
    payload = mcp.ok(call("save_document", path=str(target)))
    assert payload["saved_path"] == str(target)
    assert fusion.document.isSaved is True


def test_export_document_requires_an_active_design(fusion_empty, call, mcp):
    message = mcp.error(call("export_document", format="step", path="/tmp/x.step"))
    assert "requires an active Fusion design" in message


def test_export_document_rejects_unsupported_format(fusion, call, mcp):
    assert mcp.error_kind(call("export_document", format="ply", path="/tmp/x.ply")) == "invalid_value"


def test_export_document_writes_a_real_file(fusion, tmp_path, call, mcp):
    target = tmp_path / "out.step"
    payload = mcp.ok(call("export_document", format="step", path=str(target)))
    assert payload["format"] == "step"
    assert payload["size_bytes"] > 0
    assert target.exists()


def test_export_document_stl_reports_density_and_units(fusion, tmp_path, call, mcp):
    target = tmp_path / "out.stl"
    payload = mcp.ok(call(
        "export_document", format="stl", path=str(target),
        stl_density="high", stl_units="mm",
    ))
    assert payload["stl_density"] == "high"
    assert payload["stl_units"] == "mm"


def test_export_document_rejects_bad_stl_density(fusion, tmp_path, call, mcp):
    target = tmp_path / "out.stl"
    message = mcp.error(call(
        "export_document", format="stl", path=str(target), stl_density="ultra",
    ))
    assert "stl_density must be one of" in message


def test_export_document_reports_missing_pdf_capability(fusion, tmp_path, call, mcp):
    # Simulate a Fusion build whose ExportManager cannot emit PDF.  The tool
    # must report it rather than silently doing nothing.
    fusion.design.exportManager.createPDFExportOptions = None
    target = tmp_path / "out.pdf"
    message = mcp.error(call("export_document", format="pdf", path=str(target)))
    assert "cannot export 'pdf'" in message


def test_close_document_requires_an_active_document(fusion_empty, call, mcp):
    assert mcp.error_kind(call("close_document")) == "no_active_document"


def test_close_document_discards_unsaved_by_default(fusion, call, mcp):
    payload = mcp.ok(call("close_document"))
    assert payload == {"closed": True}
    assert fusion.document.closed is True


def test_close_document_named_other_document(fusion, tmp_path, call, mcp):
    other = fusion.new_document("Other")
    fusion.app._activate(fusion.documents.itemByName("Test Design"))
    payload = mcp.ok(call("close_document", document_name="Other"))
    assert payload == {"closed": True}
    assert other.closed is True


def test_close_document_refuses_to_save_without_a_location(fusion, call, mcp):
    assert mcp.error_kind(call("close_document", save=True)) == "unsupported_operation"


def test_close_document_saves_first_when_asked(fusion, tmp_path, call, mcp):
    mcp.ok(call("save_document", path=str(tmp_path / "c.f3d")))
    fusion.document.isModified = True
    payload = mcp.ok(call("close_document", save=True))
    assert payload == {"closed": True}
    assert fusion.document.isModified is False


def test_get_document_info_reports_saved_state(fusion, tmp_path, call, mcp):
    target = tmp_path / "info.f3d"
    mcp.ok(call("save_document", path=str(target)))
    payload = mcp.ok(call("get_document_info"))
    assert payload["name"] == "info.f3d"
    assert payload["path"] == str(target)
    assert payload["design_type"] == "parametric"
    assert payload["units"] == "cm"


def test_get_document_info_without_a_document(fusion_empty, call, mcp):
    assert mcp.error_kind(call("get_document_info")) == "no_active_document"


def test_export_document_reports_execute_failure_without_silent_success(
    fusion, monkeypatch, tmp_path, call, mcp
):
    target = tmp_path / "fail.step"

    def boom(self, options):
        raise RuntimeError("simulated Fusion failure")

    monkeypatch.setattr(fusion.design.exportManager, "execute", boom)
    message = mcp.error(call("export_document", format="step", path=str(target)))
    assert "failed to export" in message
    assert not os.path.exists(target)
