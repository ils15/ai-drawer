"""Document lifecycle tools: create, open, save, export, close, inspect."""

import contextlib
import os

import adsk.core
import adsk.fusion

from . import (
    active_app,
    active_design,
    active_document,
    bool_or_none,
    error_result,
    optional_bool,
    optional_str,
    require,
    safe_get,
    success_result,
)
from .lifecycle import _design_type_name, _design_units

DESIGN_TYPES = ("parametric", "direct")
EXPORT_FORMATS = ("step", "stl", "f3d", "iges", "obj", "pdf")
STL_DENSITY_MEMBERS = {
    "low": "MeshRefinementLow",
    "medium": "MeshRefinementMedium",
    "high": "MeshRefinementHigh",
}
STL_UNIT_MEMBERS = {
    "mm": "MillimeterDistanceUnits",
    "cm": "CentimeterDistanceUnits",
    "in": "InchDistanceUnits",
    "m": "MeterDistanceUnits",
}


def _design_type_argument(arguments):
    """Validate the optional design_type argument shared by new_document."""
    design_type = arguments.get("design_type", "parametric")
    if design_type is None:
        return "parametric"
    if design_type not in DESIGN_TYPES:
        raise ValueError(f"design_type must be one of {', '.join(DESIGN_TYPES)}")
    return design_type


def _find_document(documents, name):
    """Locate an open document by name (itemByName when available)."""
    if documents is None:
        return None
    finder = getattr(documents, "itemByName", None)
    if callable(finder):
        try:
            document = finder(name)
        except Exception:
            document = None
        if document is not None:
            return document
    for index in range(safe_get(documents, "count", 0) or 0):
        document = documents.item(index)
        if safe_get(document, "name") == name:
            return document
    return None

def _file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def _set_enum(target, prop, enum_class, member):
    """Assign an SDK enum member, silently skipping anything unsupported."""
    value = getattr(enum_class, member, None)
    if value is None:
        return
    with contextlib.suppress(Exception):
        setattr(target, prop, value)


def new_document(arguments):
    """Create and activate a new Fusion design document."""
    try:
        name = require(arguments, "name")["name"]
        design_type = _design_type_argument(arguments)
        documents = safe_get(active_app(), "documents")
        if documents is None:
            return error_result("Error: the Fusion document collection is unavailable")
        document = documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        if document is None:
            return error_result("Error: Fusion refused to create a new document")
        with contextlib.suppress(Exception):
            document.name = name
        actual_type = "parametric"
        if design_type == "direct":
            design = active_design()
            member = getattr(adsk.fusion.DesignTypes, "DirectDesignType", None)
            if design is None or member is None:
                return error_result("Error: created the document but could not switch it to direct modeling")
            try:
                design.designType = member
            except Exception as exc:
                return error_result(f"Error: created the document but direct modeling failed: {exc}")
            actual_type = "direct"
        return success_result({"document_name": safe_get(document, "name"), "design_type": actual_type})
    except Exception as exc:
        return error_result(f"Error creating document: {exc}")


def open_document(arguments):
    """Open a previously saved Fusion file by path."""
    try:
        path = require(arguments, "path")["path"]
        documents = safe_get(active_app(), "documents")
        if documents is None:
            return error_result("Error: the Fusion document collection is unavailable")
        document = documents.open(path)
        if document is None:
            return error_result(f"Error: Fusion could not open '{path}' (check the path and file type)")
        return success_result({
            "document_name": safe_get(document, "name"),
            "is_modified": bool_or_none(safe_get(document, "isModified")),
        })
    except Exception as exc:
        return error_result(f"Error opening document: {exc}")


def save_document(arguments):
    """Save the active document in place, or to *path* for a first save / save-as."""
    try:
        path = optional_str(arguments, "path")
        document = active_document()
        if document is None:
            return error_result("Error: no active document to save")
        if path:
            folder, _, name = path.replace("\\", "/").rpartition("/")
            try:
                ok = document.saveAs(name, folder, "", "")
            except Exception as exc:
                return error_result(f"Error: Fusion could not save '{path}': {exc}")
            if not ok:
                return error_result(f"Error: Fusion could not save '{path}'")
            saved_path = path
        else:
            if not safe_get(document, "isSaved"):
                return error_result(
                    "Error: the active document has never been saved; provide a path to save it to"
                )
            try:
                ok = document.save()
            except Exception as exc:
                return error_result(f"Error: Fusion could not save the active document: {exc}")
            if not ok:
                return error_result("Error: Fusion could not save the active document")
            data_file = safe_get(document, "dataFile")
            saved_path = safe_get(data_file, "path")
        return success_result({"saved_path": saved_path})
    except Exception as exc:
        return error_result(f"Error saving document: {exc}")


def _build_export_options(manager, design, fmt, path, arguments):
    """Create the ExportOptions object for *fmt*, or None when unsupported."""
    root = safe_get(design, "rootComponent")
    if fmt == "step":
        return manager.createSTEPExportOptions(path)
    if fmt == "iges":
        return manager.createIGESExportOptions(path)
    if fmt == "f3d":
        return manager.createFusionArchiveExportOptions(path)
    if fmt == "obj":
        return manager.createOBJExportOptions(root, path)
    if fmt == "stl":
        options = manager.createSTLExportOptions(root, path)
        density = arguments.get("stl_density", "medium")
        if density not in STL_DENSITY_MEMBERS:
            raise ValueError(f"stl_density must be one of {', '.join(STL_DENSITY_MEMBERS)}")
        _set_enum(options, "meshRefinement", adsk.fusion.MeshRefinementSettings, STL_DENSITY_MEMBERS[density])
        units = arguments.get("stl_units")
        if units:
            if units not in STL_UNIT_MEMBERS:
                raise ValueError(f"stl_units must be one of {', '.join(STL_UNIT_MEMBERS)}")
            _set_enum(options, "unitType", adsk.fusion.DistanceUnits, STL_UNIT_MEMBERS[units])
        return options
    if fmt == "pdf":
        creator = getattr(manager, "createPDFExportOptions", None)
        if creator is None:
            return None
        return creator(path)
    return None


def export_document(arguments):
    """Export the active design to STEP, STL, F3D, IGES, OBJ, or PDF."""
    try:
        fmt = require(arguments, "format")["format"]
        path = require(arguments, "path")["path"]
        if fmt not in EXPORT_FORMATS:
            return error_result(
                f"Error: unsupported export format '{fmt}'; supported: {', '.join(EXPORT_FORMATS)}"
            )
        design = active_design()
        if design is None:
            return error_result(
                "Error: exporting requires an active Fusion design; open or create a document first"
            )
        manager = safe_get(design, "exportManager")
        if manager is None:
            return error_result("Error: the active design has no export manager")
        options = _build_export_options(manager, design, fmt, path, arguments)
        if options is None:
            return error_result(
                f"Error: this Fusion build cannot export '{fmt}' (the ExportManager lacks the creator)"
            )
        try:
            ok = manager.execute(options)
        except Exception as exc:
            return error_result(f"Error: Fusion failed to export '{fmt}' to '{path}': {exc}")
        if not ok:
            return error_result(f"Error: Fusion failed to export '{fmt}' to '{path}'")
        result = {"path": path, "format": fmt, "size_bytes": _file_size(path)}
        if fmt == "stl":
            result["stl_density"] = arguments.get("stl_density", "medium")
            units = arguments.get("stl_units")
            if units:
                result["stl_units"] = units
        return success_result(result)
    except Exception as exc:
        return error_result(f"Error exporting document: {exc}")


def close_document(arguments):
    """Close the active document, or the one named by *document_name*."""
    try:
        save = optional_bool(arguments, "save")
        document = active_document()
        if document is None:
            return error_result("Error: no active document to close")
        name = optional_str(arguments, "document_name")
        if name:
            document = _find_document(safe_get(active_app(), "documents"), name)
            if document is None:
                return error_result(f"Error: no open document named '{name}'")
        if save:
            if not safe_get(document, "isSaved"):
                return error_result(
                    "Error: cannot save an unsaved document while closing; save it to a path first"
                )
            try:
                document.save()
            except Exception as exc:
                return error_result(f"Error: saving before close failed: {exc}")
        try:
            closed = document.close(False)
        except Exception as exc:
            return error_result(f"Error: Fusion could not close the document: {exc}")
        return success_result({"closed": bool(closed)})
    except Exception as exc:
        return error_result(f"Error closing document: {exc}")


def get_document_info(arguments):
    """Report name, path, units, design type, modified flag, and version."""
    try:
        document = active_document()
        if document is None:
            return error_result("Error: no active document")
        design = active_design()
        data_file = safe_get(document, "dataFile")
        return success_result({
            "name": safe_get(document, "name"),
            "path": safe_get(data_file, "path"),
            "units": _design_units(design),
            "design_type": _design_type_name(design),
            "is_modified": bool_or_none(safe_get(document, "isModified")),
            "version": safe_get(data_file, "version"),
        })
    except Exception as exc:
        return error_result(f"Error reading document info: {exc}")
