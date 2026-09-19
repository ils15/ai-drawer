"""Fusion process, document, and design status tools."""

import time

import adsk.fusion

from . import (
    active_app,
    active_design,
    active_document,
    bool_or_none,
    error_result,
    safe_get,
    success_result,
)

_START_TIME = time.monotonic()

_DESIGN_TYPE_MEMBERS = (("parametric", "ParametricDesignType"), ("direct", "DirectDesignType"))


def _design_type_name(design):
    """Map a ``Design.designType`` enum value to its wire name, or None."""
    if design is None:
        return None
    try:
        value = design.designType
        types = adsk.fusion.DesignTypes
    except Exception:
        return None
    for name, member in _DESIGN_TYPE_MEMBERS:
        try:
            if value == getattr(types, member):
                return name
        except Exception:
            continue
    return None


def _design_units(design):
    """Return the design's default length unit string, or None."""
    if design is None:
        return None
    manager = safe_get(design, "unitsManager") or safe_get(design, "fusionUnitsManager")
    units = safe_get(manager, "defaultLengthUnits")
    if units:
        return units
    display = safe_get(manager, "distanceDisplayUnits")
    return _distance_unit_name(display)


def _distance_unit_name(value):
    for name, member in (
        ("mm", "MillimeterDistanceUnits"),
        ("cm", "CentimeterDistanceUnits"),
        ("m", "MeterDistanceUnits"),
        ("in", "InchDistanceUnits"),
    ):
        try:
            if value == getattr(adsk.fusion.DistanceUnits, member):
                return name
        except Exception:
            continue
    return None


def _document_design_type(document):
    """Best-effort design type for an arbitrary open document."""
    product = safe_get(document, "product")
    if product is None:
        return None
    try:
        return _design_type_name(adsk.fusion.Design.cast(product))
    except Exception:
        return None


def _document_summary(document):
    """Build one entry for list_documents."""
    if document is None:
        return None
    is_active = bool_or_none(safe_get(document, "isActive"))
    design_type = _document_design_type(document)
    if is_active and design_type is None:
        design_type = _design_type_name(active_design())
    data_file = safe_get(document, "dataFile")
    return {
        "name": safe_get(document, "name"),
        "is_active": is_active,
        "is_modified": bool_or_none(safe_get(document, "isModified")),
        "design_type": design_type,
        "saved_path": safe_get(data_file, "path"),
    }


def fusion_status(arguments):
    """Report the Fusion version, active document/design, units, and timeline size.

    Works without an open document: the document-related fields are then null.
    """
    try:
        app = active_app()
        design = active_design()
        document = active_document()
        timeline = safe_get(design, "timeline")
        workspace = safe_get(safe_get(app, "userInterface"), "activeWorkspace")
        payload = {
            "fusion_version": safe_get(app, "version"),
            "document_name": safe_get(document, "name"),
            "is_modified": bool_or_none(safe_get(document, "isModified")),
            "units": _design_units(design),
            "design_type": _design_type_name(design),
            "workspace": safe_get(workspace, "name"),
            "timeline_feature_count": safe_get(timeline, "count"),
            "addin_uptime_s": round(time.monotonic() - _START_TIME, 3),
        }
        return success_result(payload)
    except Exception as exc:
        return error_result(f"Error reading Fusion status: {exc}")


def list_documents(arguments):
    """List every document currently open in Fusion."""
    try:
        documents = safe_get(active_app(), "documents")
        count = safe_get(documents, "count", 0) or 0
        items = []
        for index in range(count):
            summary = _document_summary(documents.item(index))
            if summary is not None:
                items.append(summary)
        return success_result({"count": len(items), "documents": items})
    except Exception as exc:
        return error_result(f"Error listing documents: {exc}")
