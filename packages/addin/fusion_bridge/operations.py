"""MCP tool routing for the Fusion bridge.

Tool definitions live in :mod:`fusion_bridge.tool_surface`; this module wires
each definition to the handler that implements it.
"""

from . import (
    doc_lookup,
    selection,
    tool_surface,
    viewport,
)
from .dispatch import log
from .tools import diagnostics, documents, features, lifecycle, parameters

# -- Wrapper helpers for handlers that take arguments directly ---------------


def _wrap(fn):
    """Wrap a handler that expects an arguments dict to accept call_data envelope."""

    def wrapper(call_data):
        params = call_data.get("params", {})
        arguments = params.get("arguments", {})
        return fn(arguments)

    return wrapper


def _wrap_doc(fn):
    """Wrap doc_lookup handlers that expect (arguments, log_fn)."""

    def wrapper(call_data):
        params = call_data.get("params", {})
        arguments = params.get("arguments", {})
        return fn(arguments, log)

    return wrapper


# -- Handler registry -------------------------------------------------------

TOOL_HANDLERS = tool_surface.build_tool_handlers(
    capture_viewport=_wrap(viewport.capture),
    get_viewport=_wrap(viewport.get_viewport),
    set_viewport=_wrap(viewport.set_viewport),
    fetch_api_documentation=_wrap_doc(doc_lookup.fetch_api_documentation),
    fetch_online_documentation=_wrap_doc(doc_lookup.fetch_online_documentation),
    fetch_design_guide=_wrap_doc(doc_lookup.fetch_design_guide),
    get_active_selection=_wrap(selection.get_active_selection),
    fusion_status=_wrap(lifecycle.fusion_status),
    fusion_diagnostics=_wrap(diagnostics.snapshot),
    list_documents=_wrap(lifecycle.list_documents),
    new_document=_wrap(documents.new_document),
    open_document=_wrap(documents.open_document),
    save_document=_wrap(documents.save_document),
    export_document=_wrap(documents.export_document),
    close_document=_wrap(documents.close_document),
    get_document_info=_wrap(documents.get_document_info),
    list_parameters=_wrap(parameters.list_parameters),
    add_parameter=_wrap(parameters.add_parameter),
    modify_parameter=_wrap(parameters.modify_parameter),
    fillet=_wrap(features.fillet),
    chamfer=_wrap(features.chamfer),
    hole=_wrap(features.hole),
    rectangular_pattern=_wrap(features.rectangular_pattern),
    circular_pattern=_wrap(features.circular_pattern),
)
