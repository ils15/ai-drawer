"""User and model parameter tools: list, add, and modify."""

import adsk.core

from . import (
    active_design,
    error_result,
    optional_str,
    require,
    safe_get,
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


def list_parameters(arguments):
    """List every user and model parameter in the active design.

    ``value`` is the evaluated number in the parameter's internal units
    (centimeters for lengths); ``expression`` is the Fusion expression string.
    """
    try:
        design = active_design()
        if design is None:
            return error_result("Error: no active Fusion design; open or create a document first")
        params = [
            *_collect_parameters(safe_get(design, "userParameters"), "user"),
            *_collect_parameters(safe_get(design, "modelParameters"), "model"),
        ]
        return success_result({"count": len(params), "parameters": params})
    except Exception as exc:
        return error_result(f"Error listing parameters: {exc}")


def add_parameter(arguments):
    """Add a user parameter driven by a Fusion expression string."""
    try:
        name = require(arguments, "name")["name"]
        expression = require(arguments, "expression")["expression"]
        unit = optional_str(arguments, "unit") or DEFAULT_PARAMETER_UNIT
        design = active_design()
        if design is None:
            return error_result("Error: no active Fusion design; open or create a document first")
        user_parameters = safe_get(design, "userParameters")
        if user_parameters is None:
            return error_result("Error: the active design has no user parameter collection")
        if _find_parameter(design, name) is not None:
            return error_result(f"Error: a parameter named '{name}' already exists in the active design")
        try:
            value_input = adsk.core.ValueInput.createByString(str(expression))
            param = user_parameters.add(name, value_input, unit, "")
        except Exception as exc:
            return error_result(
                f"Error: Fusion refused to create parameter '{name}' (check the expression and unit): {exc}"
            )
        if param is None:
            return error_result(f"Error: Fusion refused to create parameter '{name}'")
        return success_result({
            "name": safe_get(param, "name"),
            "expression": safe_get(param, "expression"),
            "value": safe_get(param, "value"),
        })
    except Exception as exc:
        return error_result(f"Error adding parameter: {exc}")


def modify_parameter(arguments):
    """Set a parameter's expression and recompute the model.

    This is the cheapest edit path: one expression write followed by a single
    full-timeline recompute.  ``recomputed_feature_count`` is the number of
    features that re-evaluated; it is null when the running Fusion cannot
    report per-feature recompute counts.
    """
    try:
        name = require(arguments, "name")["name"]
        expression = require(arguments, "expression")["expression"]
        design = active_design()
        if design is None:
            return error_result("Error: no active Fusion design; open or create a document first")
        param = _find_parameter(design, name)
        if param is None:
            return error_result(f"Error: no parameter named '{name}' in the active design")
        try:
            param.expression = str(expression)
        except Exception as exc:
            return error_result(f"Error: Fusion rejected the expression for '{name}': {exc}")
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
    except Exception as exc:
        return error_result(f"Error modifying parameter: {exc}")
