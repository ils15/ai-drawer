"""User and model parameter tools: list, add, and modify."""

import adsk.core

from . import (
    active_design,
    map_tool_errors,
    optional_str,
    require,
    safe_get,
    structured_error,
    success_result,
)

DEFAULT_PARAMETER_UNIT = "mm"


def _parameter_summary(param, kind):
    """Build one entry for list_parameters."""
    return {
        "name": safe_get(param, "name"),
        "expression": safe_get(param, "expression"),
        "unit": safe_get(param, "unit"),
        "value": safe_get(param, "value"),
        "parameter_type": kind,
        "driven": bool(safe_get(param, "isDriven", False)),
    }


def _collect_parameters(collection, kind):
    """Flatten one parameter collection into wire summaries."""
    if collection is None:
        return []
    count = safe_get(collection, "count", 0) or 0
    items = []
    for index in range(count):
        param = collection.item(index)
        if param is not None:
            items.append(_parameter_summary(param, kind))
    return items


def _find_parameter(design, name):
    """Find a parameter by name in user then model parameters."""
    for attr in ("userParameters", "modelParameters"):
        collection = safe_get(design, attr)
        finder = getattr(collection, "itemByName", None)
        if callable(finder):
            try:
                param = finder(name)
            except Exception:
                param = None
            if param is not None:
                return param
    return None


_NO_DESIGN = "No active Fusion design; open or create a document first"


@map_tool_errors
def list_parameters(arguments):
    """List every user and model parameter in the active design.

    ``value`` is the evaluated number in the parameter's internal units
    (centimeters for lengths); ``expression`` is the Fusion expression string.
    """
    del arguments
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    params = [
        *_collect_parameters(safe_get(design, "userParameters"), "user"),
        *_collect_parameters(safe_get(design, "modelParameters"), "model"),
    ]
    return success_result({"count": len(params), "parameters": params})


@map_tool_errors
def add_parameter(arguments):
    """Add a user parameter driven by a Fusion expression string."""
    name = require(arguments, "name")["name"]
    expression = require(arguments, "expression")["expression"]
    unit = optional_str(arguments, "unit") or DEFAULT_PARAMETER_UNIT
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    user_parameters = safe_get(design, "userParameters")
    if user_parameters is None:
        return structured_error(
            "internal", "The active design has no user parameter collection"
        )
    if _find_parameter(design, name) is not None:
        return structured_error(
            "parameter_already_exists",
            f"A parameter named '{name}' already exists in the active design",
        )
    try:
        value_input = adsk.core.ValueInput.createByString(str(expression))
        param = user_parameters.add(name, value_input, unit, "")
    except ValueError as exc:
        # Fusion itself reports a duplicate name when the caller races another
        # client; report it as a duplicate rather than a bad expression.
        if "already exists" in str(exc):
            return structured_error(
                "parameter_already_exists",
                f"A parameter named '{name}' already exists in the active design",
            )
        return structured_error(
            "invalid_expression",
            f"Fusion rejected the expression or unit for '{name}' (check the expression and unit)",
        )
    except Exception:
        return structured_error(
            "invalid_expression",
            f"Fusion rejected the expression or unit for '{name}' (check the expression and unit)",
        )
    if param is None:
        return structured_error(
            "invalid_expression", f"Fusion refused to create parameter '{name}'"
        )
    return success_result({
        "name": safe_get(param, "name"),
        "expression": safe_get(param, "expression"),
        "value": safe_get(param, "value"),
    })


@map_tool_errors
def modify_parameter(arguments):
    """Set a parameter's expression and recompute the model.

    This is the cheapest edit path: one expression write followed by a single
    full-timeline recompute.  ``recomputed_feature_count`` is the number of
    features that re-evaluated; it is null when the running Fusion cannot
    report per-feature recompute counts.
    """
    name = require(arguments, "name")["name"]
    expression = require(arguments, "expression")["expression"]
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    param = _find_parameter(design, name)
    if param is None:
        return structured_error(
            "parameter_not_found", f"No parameter named '{name}' in the active design"
        )
    try:
        param.expression = str(expression)
    except Exception:
        return structured_error(
            "invalid_expression", f"Fusion rejected the expression for '{name}'"
        )
    did_recompute = False
    recomputed = None
    compute_all = getattr(design, "computeAll", None)
    if callable(compute_all):
        did_recompute = bool(compute_all())
        recomputed = safe_get(design, "recomputedFeatureCount")
    return success_result({
        "name": name,
        "expression": safe_get(param, "expression"),
        "value": safe_get(param, "value"),
        "did_recompute": did_recompute,
        "recomputed_feature_count": recomputed,
    })
