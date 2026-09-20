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

import math

import adsk.core
import adsk.fusion

from ..value_builders import OBJECT_STORE, FusionContext
from . import (
    MissingArgument,
    active_app,
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


def _store(kind, obj):
    """Stash a created object and return the handle later tools address it by.

    ``$selection_N`` entries come from ``get_active_selection``; tools that
    *create* geometry publish their own handles on the same store so a caller
    can chain ``create_sketch`` -> ``extrude`` -> ``apply_appearance`` without
    a reverse lookup the bridge does not keep.
    """
    index = 0
    while f"{kind}_{index}" in OBJECT_STORE:
        index += 1
    OBJECT_STORE[f"{kind}_{index}"] = obj
    return f"${kind}_{index}"


def _numeric(value, name):
    """Coerce an argument to a plain number, rejecting anything non-numeric."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return float(value)


def _positive_number(value, name):
    """A dimension in centimetres: present, numeric, and strictly positive."""
    value = _numeric(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _point3d(value, name="point"):
    """Build a ``Point3D`` from an ``{x, y, z}`` object given in centimetres."""
    try:
        return adsk.core.Point3D.create(float(value["x"]), float(value["y"]), float(value["z"]))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an object with numeric x, y, and z in centimetres") from exc


# A construction plane is reached as an attribute of the root component.  The
# published names pair the two axes the plane spans; "xz" is published as the
# zX plane, with the reversed spelling tolerated because the reference is not
# consistent across builds.
_PLANE_ATTRIBUTES = {
    "xy": ("xYConstructionPlane",),
    "xz": ("zXConstructionPlane", "xZConstructionPlane"),
    "yz": ("yZConstructionPlane",),
}
_AXIS_ATTRIBUTES = {
    "x": ("xConstructionAxis",),
    "y": ("yConstructionAxis",),
    "z": ("zConstructionAxis",),
}


def _named_entity(root, candidates, kind, given):
    """Resolve one of several attribute names on the root component."""
    for attribute in candidates:
        found = safe_get(root, attribute)
        if found is not None:
            return found
    return None


def _feature_operation(name):
    """Map a schema operation name to its ``FeatureOperations`` enumerator."""
    operations = {
        "new_body": "NewBodyFeatureOperation",
        "join": "JoinFeatureOperation",
        "cut": "CutFeatureOperation",
        "intersect": "IntersectFeatureOperation",
    }
    member = operations.get(name)
    if member is None:
        raise ValueError("operation must be one of 'new_body', 'join', 'cut', or 'intersect'")
    return getattr(adsk.fusion.FeatureOperations, member)


def _extent_direction(name):
    """Map a schema direction name to its ``ExtentDirections`` enumerator."""
    if name == "positive":
        return adsk.fusion.ExtentDirections.PositiveExtentDirection
    if name == "negative":
        return adsk.fusion.ExtentDirections.NegativeExtentDirection
    raise ValueError("direction must be 'positive' or 'negative'")


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


# ── Sketch, extrude, and revolve ─────────────────────────────────────────────
#
# These three are the modelling spine: ``create_sketch`` draws on a base plane
# and hands back the closed profiles it produced as handles, ``extrude`` and
# ``revolve`` consume one of those profile handles to make solid geometry.  A
# caller never names a profile by index -- the sketch tool publishes
# ``$profile_0`` because there is no other way to know which closed region the
# API decided a set of curves formed.


def _add_curve(sketch, curve):
    """Append one line, circle, or arc to a sketch, in centimetres."""
    if not isinstance(curve, dict):
        raise ValueError("each curve must be an object")
    kind = curve.get("kind")
    curves = sketch.sketchCurves
    if kind == "line":
        start = _point3d(curve.get("start"), "start")
        end = _point3d(curve.get("end"), "end")
        return curves.sketchLines.addByTwoPoints(start, end)
    if kind == "circle":
        center = _point3d(curve.get("center"), "center")
        radius = _positive_number(curve.get("radius"), "radius")
        return curves.sketchCircles.addByCenterRadius(center, radius)
    if kind == "arc":
        center = _point3d(curve.get("center"), "center")
        start = _point3d(curve.get("start"), "start")
        sweep = _numeric(curve.get("sweep"), "sweep")
        # The API takes the sweep in radians, positive being counter-clockwise;
        # the schema carries friendlier degrees.
        return curves.sketchArcs.addByCenterStartSweep(center, start, math.radians(sweep))
    raise ValueError("curve kind must be 'line', 'circle', or 'arc'")


@map_tool_errors
def create_sketch(arguments):
    """Draw one or more curves on a base construction plane of the root component.

    ``plane`` is ``xy``, ``xz``, or ``yz``; ``curves`` is an array of line,
    circle, and arc descriptors with coordinates in centimetres (arcs carry a
    ``sweep`` in *degrees*, counter-clockwise positive).  The sketch and every
    closed profile Fusion derives from the curves are returned as handles --
    ``$profile_0`` is what ``extrude`` and ``revolve`` consume.  Profiles are
    populated by the sketch itself, so an open curve chain yields none.
    """
    plane_name = require(arguments, "plane")["plane"]
    curve_specs = require(arguments, "curves")["curves"]
    if not isinstance(curve_specs, (list, tuple)):
        raise ValueError("curves must be an array")
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    if plane_name not in _PLANE_ATTRIBUTES:
        raise ValueError("plane must be 'xy', 'xz', or 'yz'")
    if not curve_specs:
        raise ValueError("curves must contain at least one curve")
    root = safe_get(design, "rootComponent")
    plane = _named_entity(root, _PLANE_ATTRIBUTES[plane_name], "plane", plane_name)
    if plane is None:
        return structured_error(
            "unsupported_operation",
            f"This Fusion build does not expose the {plane_name.upper()} construction plane",
        )
    sketches = safe_get(root, "sketches")
    if sketches is None:
        return structured_error("unsupported_operation", "This Fusion build cannot create a sketch")
    sketch = sketches.add(plane)
    for curve in curve_specs:
        _add_curve(sketch, curve)
    profiles = safe_get(sketch, "profiles")
    profile_handles = []
    if profiles is not None:
        for index in range(safe_get(profiles, "count", 0) or 0):
            profile_handles.append(_store("profile", profiles.item(index)))
    return success_result(
        {
            "sketch": _store("sketch", sketch),
            "name": safe_get(sketch, "name"),
            "plane": plane_name,
            "curve_count": len(curve_specs),
            "profiles": profile_handles,
            "profile_count": len(profile_handles),
        }
    )


@map_tool_errors
def extrude(arguments):
    """Sweep a closed profile into a solid by a distance, through all, or symmetric.

    ``profile`` is a handle from ``create_sketch``; ``operation`` says how the
    new geometry combines with existing bodies; ``extent`` picks a fixed
    ``distance`` (needs the ``distance`` argument), ``through_all``, or a
    ``symmetric`` sweep about the profile plane (also needs ``distance``);
    ``direction`` applies to the one-sided extents.
    """
    profile_ref = require(arguments, "profile")["profile"]
    operation = arguments.get("operation", "new_body")
    extent = arguments.get("extent", "distance")
    distance = arguments.get("distance")
    direction = arguments.get("direction", "positive")
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    if extent not in ("distance", "through_all", "symmetric"):
        raise ValueError("extent must be 'distance', 'through_all', or 'symmetric'")
    if extent in ("distance", "symmetric") and not distance:
        raise ValueError("distance is required when extent is 'distance' or 'symmetric'")
    profile = _resolve_entity(profile_ref, design)
    extrude_features, error = _feature_collection(design, "extrudeFeatures")
    if error is not None:
        return error
    extrude_input = extrude_features.createInput(profile, _feature_operation(operation))
    if extent == "symmetric":
        extrude_input.setSymmetricExtent(adsk.fusion.DistanceExtentDefinition.create(_to_value_input(distance)))
    elif extent == "distance":
        extrude_input.setOneSideExtent(
            adsk.fusion.DistanceExtentDefinition.create(_to_value_input(distance)),
            _extent_direction(direction),
        )
    else:
        extrude_input.setOneSideExtent(adsk.fusion.ThroughAllExtentDefinition.create(), _extent_direction(direction))
    feature = extrude_features.add(extrude_input)
    if feature is None:
        return _refused("extrude")
    bodies = safe_get(feature, "bodies")
    body_handle = None
    if bodies is not None and safe_get(bodies, "count", 0):
        body_handle = _store("body", bodies.item(0))
    return success_result(
        {
            "feature": safe_get(feature, "name"),
            "feature_type": "Extrude",
            "profile": profile_ref,
            "operation": operation,
            "extent": extent,
            "distance": distance if extent != "through_all" else None,
            "direction": None if extent == "symmetric" else direction,
            "body": body_handle,
        }
    )


@map_tool_errors
def revolve(arguments):
    """Sweep a closed profile about an axis through an angle to make a solid.

    ``profile`` is a handle from ``create_sketch``; ``axis`` is either a stored
    handle to a linear edge or axis, or one of the strings ``x``, ``y``, or
    ``z`` for the root component's construction axes.  ``angle`` is a Fusion
    angle expression and defaults to a full 360-degree turn.
    """
    profile_ref = require(arguments, "profile")["profile"]
    axis_ref = require(arguments, "axis")["axis"]
    operation = arguments.get("operation", "new_body")
    angle = arguments.get("angle")
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    profile = _resolve_entity(profile_ref, design)
    root = safe_get(design, "rootComponent")
    axis = (
        _named_entity(root, _AXIS_ATTRIBUTES[axis_ref], "axis", axis_ref)
        if axis_ref in _AXIS_ATTRIBUTES
        else _resolve_entity(axis_ref, design)
    )
    if axis is None:
        raise ValueError("axis must be a stored entity handle or one of 'x', 'y', or 'z'")
    revolve_features, error = _feature_collection(design, "revolveFeatures")
    if error is not None:
        return error
    # A full turn, expressed the way the API's own defaults do.
    angle_value = _to_value_input(angle) if angle else adsk.core.ValueInput.createByReal(2 * math.pi)
    revolve_input = revolve_features.createInput(profile, axis, _feature_operation(operation))
    revolve_input.setAngleExtent(False, angle_value)
    feature = revolve_features.add(revolve_input)
    if feature is None:
        return _refused("revolve")
    return success_result(
        {
            "feature": safe_get(feature, "name"),
            "feature_type": "Revolve",
            "profile": profile_ref,
            "axis": axis_ref,
            "operation": operation,
            "angle": angle if angle else "360 deg",
        }
    )


# ── Structure and body primitives ────────────────────────────────────────────


@map_tool_errors
def create_component(arguments):
    """Add a new component to the root component's assembly.

    ``name`` becomes the new component's name.  There is no ``addComponent``:
    a component is created by adding an occurrence with an identity transform
    and naming the component that occurrence owns.
    """
    name = require(arguments, "name")["name"]
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    root = safe_get(design, "rootComponent")
    occurrences = safe_get(root, "occurrences")
    if occurrences is None or not hasattr(occurrences, "addNewComponent"):
        return structured_error(
            "unsupported_operation",
            "This Fusion build cannot add a component through occurrences",
        )
    occurrence = occurrences.addNewComponent(adsk.core.Matrix3D.create())
    if occurrence is None:
        return _refused("component")
    component = safe_get(occurrence, "component")
    if component is None:
        return structured_error(
            "unsupported_operation",
            "The new occurrence owns no component in this Fusion build",
        )
    component.name = name
    return success_result(
        {
            "component": _store("component", component),
            "occurrence": _store("occurrence", occurrence),
            "name": name,
        }
    )


def _temporary_body(shape, dimensions):
    """Build a transient solid with ``TemporaryBRepManager``, in centimetres."""
    if not isinstance(dimensions, dict):
        raise ValueError("dimensions must be an object")
    manager = adsk.fusion.TemporaryBRepManager.get()
    if shape == "box":
        length = _positive_number(dimensions.get("length"), "length")
        width = _positive_number(dimensions.get("width"), "width")
        height = _positive_number(dimensions.get("height"), "height")
        return manager.createBox(
            adsk.core.BoundingBox3D.create(
                adsk.core.Point3D.create(0.0, 0.0, 0.0),
                adsk.core.Point3D.create(length, width, height),
            )
        )
    if shape == "cylinder":
        radius = _positive_number(dimensions.get("radius"), "radius")
        height = _positive_number(dimensions.get("height"), "height")
        return manager.createCylinderOrCone(
            adsk.core.Point3D.create(0.0, 0.0, 0.0),
            adsk.core.Point3D.create(0.0, 0.0, height),
            radius,
            radius,
        )
    if shape == "sphere":
        radius = _positive_number(dimensions.get("radius"), "radius")
        return manager.createSphere(adsk.core.Point3D.create(0.0, 0.0, 0.0), radius)
    raise ValueError("shape must be 'box', 'cylinder', or 'sphere'")


@map_tool_errors
def create_body(arguments):
    """Add a primitive box, cylinder, or sphere body to the root component.

    ``dimensions`` are in centimetres: a box needs ``length``, ``width``, and
    ``height``; a cylinder needs ``radius`` and ``height``; a sphere needs
    ``radius``.  Transient geometry becomes a body through ``BRepBodies.add``;
    a parametric design wraps that in a base feature's edit cycle, a direct
    design does not.
    """
    shape = require(arguments, "shape")["shape"]
    dimensions = require(arguments, "dimensions")["dimensions"]
    name = arguments.get("name")
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    if shape not in ("box", "cylinder", "sphere"):
        raise ValueError("shape must be 'box', 'cylinder', or 'sphere'")
    temporary_body = _temporary_body(shape, dimensions)
    root = safe_get(design, "rootComponent")
    bodies = safe_get(root, "bodies")
    if bodies is None:
        return structured_error("unsupported_operation", "This Fusion build cannot add a body")
    if design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        base_features, error = _feature_collection(design, "baseFeatures")
        if error is not None:
            return error
        base_feature = base_features.add()
        base_feature.startEdit()
        body = bodies.add(temporary_body, base_feature)
        base_feature.finishEdit()
    else:
        body = bodies.add(temporary_body)
    if body is None:
        return _refused("body")
    if name:
        body.name = name
    return success_result(
        {
            "body": _store("body", body),
            "name": safe_get(body, "name"),
            "shape": shape,
            "is_solid": safe_get(body, "isSolid", True),
        }
    )


@map_tool_errors
def apply_appearance(arguments):
    """Assign a library appearance to a body.

    ``body`` is a stored handle to a BRep body; ``appearance`` names an
    appearance in ``library`` (the ``Fusion 360 Material Library`` by
    default).  The appearance is copied into the design and assigned to the
    body, so it can be recoloured later without touching the library.
    """
    body_ref = require(arguments, "body")["body"]
    appearance_name = require(arguments, "appearance")["appearance"]
    library_name = arguments.get("library", "Fusion 360 Material Library")
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    if not isinstance(appearance_name, str) or not appearance_name.strip():
        raise ValueError("appearance must be a non-empty appearance name")
    body = _resolve_entity(body_ref, design)
    libraries = safe_get(active_app(), "materialLibraries")
    item_by_name = safe_get(libraries, "itemByName")
    if libraries is None or item_by_name is None:
        return structured_error(
            "unsupported_operation",
            "This Fusion build does not expose material libraries",
        )
    library = item_by_name(library_name)
    if library is None:
        return structured_error(
            "not_found",
            f"No material library named '{library_name}' is available in this Fusion build",
        )
    source = safe_get(safe_get(library, "appearances"), "itemByName")
    if source is None:
        return structured_error(
            "unsupported_operation",
            f"The '{library_name}' library exposes no appearances in this Fusion build",
        )
    appearance = source(appearance_name)
    if appearance is None:
        return structured_error(
            "not_found",
            f"No appearance named '{appearance_name}' exists in the '{library_name}' library",
        )
    design_appearances = safe_get(design, "appearances")
    add_by_copy = safe_get(design_appearances, "addByCopy")
    if design_appearances is None or add_by_copy is None:
        return structured_error(
            "unsupported_operation",
            "This Fusion build cannot copy an appearance into the design",
        )
    assigned = add_by_copy(appearance)
    if assigned is None:
        return _refused("appearance")
    body.appearance = assigned
    return success_result(
        {
            "body": body_ref,
            "appearance": appearance_name,
            "library": library_name,
            "appearance_name": safe_get(assigned, "name"),
        }
    )
