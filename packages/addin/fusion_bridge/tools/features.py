"""Feature creation tools: fillet, chamfer, hole, and the two pattern tools.

Geometry is addressed by *stored selection handle*, not by token or name.  A
caller runs ``get_active_selection`` first, which puts whatever the user picked
into the shared object store as ``$selection_0``, ``$selection_1``, ... and then
hands those handles to these tools.  There is deliberately no entity-token
reverse lookup: tokens are stable within a session but the bridge owns no
registry mapping them back to objects, so routing through the store is the one
round trip that cannot lie about what is selected.

Lengths and angles are Fusion *expression strings* (``"5 mm"``, ``"360 deg"``)
handed to the expression engine, or bare numbers, which the API reads as internal
centimetres.  Every mutation is one-shot: a failure is reported once and never
retried, because a half-applied feature is worse than a clean error.
"""

import adsk.core
import adsk.fusion

from ..value_builders import OBJECT_STORE, FusionContext
from . import (
    MissingArgument,
    active_design,
    map_tool_errors,
    require,
    safe_get,
    structured_error,
    success_result,
)

_NO_DESIGN = "No active Fusion design; open or create a document first"


def _require_dimension(arguments, name):
    """Fetch a dimension or count, treating zero as *wrong* rather than absent.

    ``require`` is right for handles and arrays, where an empty value means
    "the caller forgot".  A radius of ``0`` or a count of ``0`` is a different
    failure: the caller passed it and it is out of range, so the range check
    below must see it and report ``invalid_value`` -- not a misleading
    ``missing_argument``.
    """
    value = arguments.get(name)
    if value is None:
        raise MissingArgument(f"missing required argument(s): {name}")
    return value


# Entity handles resolve through the same store get_active_selection fills.  The
# context is created once and pointed at that shared dict, so a handle stored by
# the selection tool is visible here without a second registry.
_entity_context = FusionContext()
_entity_context.objects = OBJECT_STORE


def _resolve_entity(ref, design):
    """Resolve a stored selection handle (``$selection_0``) to a live object.

    ``design`` is the active design the caller already validated; it is unused
    here because the object store is process-global, which is exactly how the
    selection tool and these feature tools share addresses.
    """
    del design
    if not isinstance(ref, str) or not ref.startswith("$"):
        raise ValueError(
            "entity must be a stored selection handle like '$selection_0'; "
            "call get_active_selection to capture the geometry first"
        )
    return _entity_context._resolve_stored(ref)


def _to_value_input(value):
    """Build a ``ValueInput``: numbers are reals (cm), strings are expressions."""
    if isinstance(value, bool):
        raise ValueError("a boolean is not a valid dimension")
    if isinstance(value, (int, float)):
        return adsk.core.ValueInput.createByReal(float(value))
    return adsk.core.ValueInput.createByString(str(value))


def _edges_collection(refs, design):
    """Resolve an array of edge handles into an ``ObjectCollection``."""
    if not isinstance(refs, (list, tuple)):
        raise ValueError("edges must be an array of entity handles")
    if not refs:
        raise ValueError("fillet and chamfer need at least one edge")
    collection = adsk.core.ObjectCollection.create()
    for ref in refs:
        collection.add(_resolve_entity(ref, design))
    return collection


def _entities_collection(refs, design):
    """Resolve and homogeneity-check pattern inputs into a collection."""
    if not isinstance(refs, (list, tuple)):
        raise ValueError("entities must be an array of entity handles")
    if not refs:
        raise ValueError("a pattern needs at least one entity")
    entities = [_resolve_entity(ref, design) for ref in refs]
    _validate_homogeneous(entities)
    collection = adsk.core.ObjectCollection.create()
    for entity in entities:
        collection.add(entity)
    return collection


def _validate_homogeneous(entities):
    """Pattern inputs must all be one entity kind (a hard Fusion requirement)."""
    kinds = {getattr(entity, "objectType", type(entity).__name__) for entity in entities}
    if len(kinds) > 1:
        raise ValueError("all patterned entities must be the same type; got " + ", ".join(sorted(kinds)))
    return next(iter(kinds))


def _feature_collection(design, name):
    """Return the named feature collection on the root component, or an error."""
    features = safe_get(safe_get(design, "rootComponent"), "features")
    collection = safe_get(features, name)
    if collection is None:
        return None, structured_error(
            "unsupported_operation",
            f"This Fusion build does not expose {name} on the active component",
        )
    return collection, None


def _refused(feature_type):
    """The error for Fusion accepting the input but refusing to build it."""
    return structured_error(
        "invalid_value",
        f"Fusion refused to build the {feature_type}; check the geometry and dimensions and retry",
    )


@map_tool_errors
def fillet(arguments):
    """Add a constant-radius fillet across one or more edges.

    ``edges`` are stored selection handles from ``get_active_selection``;
    ``radius`` is a Fusion expression such as ``"5 mm"``; ``is_tangent_chain``
    (default true) extends the fillet along tangentially connected edges.
    """
    edge_refs = require(arguments, "edges")["edges"]
    radius = _require_dimension(arguments, "radius")
    is_tangent_chain = arguments.get("is_tangent_chain", True)
    if not isinstance(is_tangent_chain, bool):
        raise ValueError("is_tangent_chain must be boolean")
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    edges = _edges_collection(edge_refs, design)
    fillet_features, error = _feature_collection(design, "filletFeatures")
    if error is not None:
        return error
    fillet_input = fillet_features.createInput()
    edge_sets = safe_get(fillet_input, "edgeSetInputs")
    if edge_sets is None:
        return structured_error(
            "unsupported_operation",
            "This Fusion build cannot define a fillet edge set",
        )
    edge_sets.addConstantRadiusEdgeSet(edges, _to_value_input(radius), is_tangent_chain)
    feature = fillet_features.add(fillet_input)
    if feature is None:
        return _refused("fillet")
    return success_result(
        {
            "feature": safe_get(feature, "name"),
            "feature_type": "Fillet",
            "edge_count": len(edge_refs),
            "radius": radius,
            "is_tangent_chain": is_tangent_chain,
        }
    )


@map_tool_errors
def chamfer(arguments):
    """Add an equal-distance chamfer across one or more edges.

    ``edges`` are stored selection handles from ``get_active_selection`` and
    ``distance`` is a Fusion expression such as ``"2 mm"``.  Both sides of the
    chamfer use that same distance.
    """
    edge_refs = require(arguments, "edges")["edges"]
    distance = _require_dimension(arguments, "distance")
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    edges = _edges_collection(edge_refs, design)
    chamfer_features, error = _feature_collection(design, "chamferFeatures")
    if error is not None:
        return error
    chamfer_input = chamfer_features.createInput2()
    edge_sets = safe_get(chamfer_input, "chamferEdgeSets")
    if edge_sets is None:
        return structured_error(
            "unsupported_operation",
            "This Fusion build cannot define a chamfer edge set",
        )
    edge_sets.addEqualDistanceChamferEdgeSet(edges, _to_value_input(distance), True)
    feature = chamfer_features.add(chamfer_input)
    if feature is None:
        return _refused("chamfer")
    return success_result(
        {
            "feature": safe_get(feature, "name"),
            "feature_type": "Chamfer",
            "edge_count": len(edge_refs),
            "distance": distance,
        }
    )


@map_tool_errors
def hole(arguments):
    """Drill a simple hole at a point on a planar face.

    ``face`` and ``position`` place the hole (``position`` is a point in cm);
    ``diameter`` is a Fusion expression.  ``extent`` is ``distance`` (the
    default, which needs ``depth``) or ``through_all``; ``direction`` picks
    which way the hole runs off the face normal.
    """
    face_ref = require(arguments, "face")["face"]
    position = require(arguments, "position")["position"]
    diameter = _require_dimension(arguments, "diameter")
    # The extent describes what this hole will do *in this design*, so the
    # missing-document precondition is reported first -- otherwise a caller
    # with no document open hears about a depth they cannot use yet.
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    extent = arguments.get("extent", "distance")
    if extent not in ("distance", "through_all"):
        raise ValueError("extent must be 'distance' or 'through_all'")
    depth = arguments.get("depth")
    if extent == "distance" and not depth:
        raise ValueError("depth is required when extent is 'distance'")
    direction = arguments.get("direction", "positive")
    if direction not in ("positive", "negative"):
        raise ValueError("direction must be 'positive' or 'negative'")
    face = _resolve_entity(face_ref, design)
    try:
        point = adsk.core.Point3D.create(float(position["x"]), float(position["y"]), float(position["z"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("position must be an object with numeric x, y, and z in centimetres") from exc
    hole_features, error = _feature_collection(design, "holeFeatures")
    if error is not None:
        return error
    hole_input = hole_features.createSimpleInput(_to_value_input(diameter))
    hole_input.setPositionByPoint(face, point)
    if extent == "through_all":
        extent_direction = (
            adsk.fusion.ExtentDirections.NegativeExtentDirection
            if direction == "negative"
            else adsk.fusion.ExtentDirections.PositiveExtentDirection
        )
        hole_input.setAllExtent(extent_direction)
    else:
        hole_input.setDistanceExtent(_to_value_input(depth))
    feature = hole_features.add(hole_input)
    if feature is None:
        return _refused("hole")
    return success_result(
        {
            "feature": safe_get(feature, "name"),
            "feature_type": "Hole",
            "diameter": diameter,
            "extent": extent,
            "depth": depth if extent == "distance" else None,
            "direction": direction,
        }
    )


@map_tool_errors
def rectangular_pattern(arguments):
    """Pattern entities along one direction, optionally a second.

    ``entities`` are stored selection handles and must all be the same kind
    (all bodies or all faces, never a mix).  ``direction_one`` is a handle to a
    linear edge or axis; ``quantity_one`` is an instance count and
    ``distance_one`` the spacing.  A second direction needs all three of
    ``direction_two``, ``quantity_two``, and ``distance_two``.
    """
    entity_refs = require(arguments, "entities")["entities"]
    direction_one = require(arguments, "direction_one")["direction_one"]
    quantity_one = _require_dimension(arguments, "quantity_one")
    distance_one = _require_dimension(arguments, "distance_one")
    direction_two = arguments.get("direction_two")
    quantity_two = arguments.get("quantity_two")
    distance_two = arguments.get("distance_two")
    is_symmetric = arguments.get("is_symmetric", False)
    if not isinstance(is_symmetric, bool):
        raise ValueError("is_symmetric must be boolean")
    if quantity_one < 1:
        raise ValueError("quantity_one must be at least 1")
    if direction_two:
        if quantity_two is None or quantity_two < 1:
            raise ValueError("quantity_two must be at least 1 when direction_two is set")
        if not distance_two:
            raise ValueError("distance_two is required when direction_two is set")
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    entities = _entities_collection(entity_refs, design)
    pattern_features, error = _feature_collection(design, "rectangularPatternFeatures")
    if error is not None:
        return error
    pattern_input = pattern_features.createInput(
        entities,
        _resolve_entity(direction_one, design),
        _to_value_input(quantity_one),
        _to_value_input(distance_one),
        adsk.fusion.PatternDistanceType.SpacingPatternDistanceType,
    )
    pattern_input.isSymmetricInDirectionOne = is_symmetric
    if direction_two:
        pattern_input.directionTwoEntity = _resolve_entity(direction_two, design)
        pattern_input.quantityTwo = _to_value_input(quantity_two)
        pattern_input.distanceTwo = _to_value_input(distance_two)
        pattern_input.isSymmetricInDirectionTwo = is_symmetric
    feature = pattern_features.add(pattern_input)
    if feature is None:
        return _refused("rectangular pattern")
    return success_result(
        {
            "feature": safe_get(feature, "name"),
            "feature_type": "RectangularPattern",
            "entity_count": len(entity_refs),
            "quantity_one": quantity_one,
            "distance_one": distance_one,
            "quantity_two": quantity_two,
            "distance_two": distance_two,
            "is_symmetric": is_symmetric,
        }
    )


@map_tool_errors
def circular_pattern(arguments):
    """Pattern entities around an axis through a total angle.

    ``entities`` are stored selection handles and must all be the same kind;
    ``axis`` is a handle to a linear edge, axis, or cylindrical face;
    ``quantity`` is the instance count and ``total_angle`` a Fusion angle
    expression (``"360 deg"`` by default).
    """
    entity_refs = require(arguments, "entities")["entities"]
    axis = require(arguments, "axis")["axis"]
    quantity = _require_dimension(arguments, "quantity")
    total_angle = arguments.get("total_angle", "360 deg")
    is_symmetric = arguments.get("is_symmetric", False)
    if not isinstance(is_symmetric, bool):
        raise ValueError("is_symmetric must be boolean")
    if quantity < 1:
        raise ValueError("quantity must be at least 1")
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    entities = _entities_collection(entity_refs, design)
    pattern_features, error = _feature_collection(design, "circularPatternFeatures")
    if error is not None:
        return error
    pattern_input = pattern_features.createInput(entities, _resolve_entity(axis, design))
    pattern_input.quantity = _to_value_input(quantity)
    pattern_input.totalAngle = _to_value_input(total_angle)
    pattern_input.isSymmetric = is_symmetric
    feature = pattern_features.add(pattern_input)
    if feature is None:
        return _refused("circular pattern")
    return success_result(
        {
            "feature": safe_get(feature, "name"),
            "feature_type": "CircularPattern",
            "entity_count": len(entity_refs),
            "quantity": quantity,
            "total_angle": total_angle,
            "is_symmetric": is_symmetric,
        }
    )
