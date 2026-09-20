"""Read-only inspection tools: bodies, one entity, the timeline, and measurements.

Four tools that report what a design *contains* without changing it.  Geometry is
addressed by stored selection handle (``$selection_0``), the same round trip the
feature tools use: ``get_active_selection`` stores whatever the user picked and
these tools resolve that handle back to the very same object.  There is no
entity-token reverse lookup for the same reason -- the bridge keeps no registry,
so the store is the one address that cannot lie about what is selected.

Every handler here is read-only.  No call mutates the document, so a caller can
run them freely while exploring a design, and a wrong argument can never damage a
model.  Empty states are answers, not errors: a design with no bodies lists zero
bodies and a direct design reports an empty timeline.

Measurements deserve a caveat the tools encode explicitly: ``measureMinimumDistance``
and ``measureAngle`` accept *different* entity kinds.  Distance takes bodies,
faces, edges, and points; angle rejects bodies and non-planar faces and accepts
points, linear edges, axes, and planar faces.  The handler pre-validates the
kinds for the requested mode and reports ``invalid_value`` before the API is
reached, because an incompatible pair would otherwise raise deep inside Fusion
with a message a caller cannot act on.
"""

import math

import adsk.core
import adsk.fusion

from . import (
    active_app,
    active_design,
    map_tool_errors,
    require,
    safe_get,
    structured_error,
    success_result,
)
from .features import _resolve_entity

_NO_DESIGN = "No active Fusion design; open or create a document first"

# objectType discriminates the three BRep kinds a handle can resolve to.  The
# values are the full qualified names the runtime publishes; a face's objectType
# is always BRepFace, so the *surface* kind comes separately from
# ``face.geometry.surfaceType``.
_BODY_KIND = "adsk.fusion.BRepBody"
_FACE_KIND = "adsk.fusion.BRepFace"
_EDGE_KIND = "adsk.fusion.BRepEdge"

_MEASURE_MODES = ("distance", "angle")


def _surface_labels():
    """SurfaceTypes member -> label, resolved on every call.

    Every SurfaceTypes member is mapped, with an explicit ``"unknown"`` bucket for
    anything the running build adds or a geometry object that carries no
    surfaceType at all.  The dict is rebuilt per call rather than cached: it is
    eight entries, and a cached copy keyed by one ``adsk`` install's enum members
    would silently report ``"unknown"`` for every surface after a test fixture
    reinstalls the runtime with fresh member objects.
    """
    return {
        adsk.fusion.SurfaceTypes.PlaneSurfaceType: "plane",
        adsk.fusion.SurfaceTypes.CylinderSurfaceType: "cylinder",
        adsk.fusion.SurfaceTypes.ConeSurfaceType: "cone",
        adsk.fusion.SurfaceTypes.SphereSurfaceType: "sphere",
        adsk.fusion.SurfaceTypes.TorusSurfaceType: "torus",
        adsk.fusion.SurfaceTypes.EllipticalCylinderSurfaceType: "elliptical_cylinder",
        adsk.fusion.SurfaceTypes.EllipticalConeSurfaceType: "elliptical_cone",
        adsk.fusion.SurfaceTypes.NurbsSurfaceType: "nurbs",
    }


def _health_labels():
    """FeatureHealthStates member -> label, resolved on every call.

    All six members are mapped.  Unknown is its own label -- "the build cannot
    tell" is not a failure, and folding it into error would make a healthy but
    unreadable feature look broken.  Like ``_surface_labels`` the dict is rebuilt
    per call so a fixture that reinstalls ``adsk`` cannot leave it bound to stale
    enum members.
    """
    return {
        adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState: "healthy",
        adsk.fusion.FeatureHealthStates.WarningFeatureHealthState: "warning",
        adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState: "error",
        adsk.fusion.FeatureHealthStates.SuppressedFeatureHealthState: "suppressed",
        adsk.fusion.FeatureHealthStates.RolledBackFeatureHealthState: "rolled_back",
        adsk.fusion.FeatureHealthStates.UnknownFeatureHealthState: "unknown",
    }


def _entity_kind(entity):
    """The objectType of a resolved entity, or its Python class as a fallback."""
    return getattr(entity, "objectType", type(entity).__name__)


def _point_dict(point):
    """A 3D point as ``{x, y, z}`` in centimetres, or None when unavailable."""
    if point is None:
        return None
    try:
        return {"x": float(point.x), "y": float(point.y), "z": float(point.z)}
    except (AttributeError, TypeError, ValueError):
        return None


def _box_dict(entity):
    """The tight-fitting bounding box of an entity, in centimetres.

    ``preciseBoundingBox`` (tight-fit) is preferred; ``boundingBox`` (rough) is
    the fallback for builds that predate it.  Both publish the span through
    ``minPoint`` / ``maxPoint``.
    """
    box = safe_get(entity, "preciseBoundingBox") or safe_get(entity, "boundingBox")
    if box is None:
        return None
    return {
        "min": _point_dict(safe_get(box, "minPoint")),
        "max": _point_dict(safe_get(box, "maxPoint")),
    }


def _surface_kind(face):
    """The mapped surface kind of a face, ``"unknown"`` when it cannot be read."""
    geometry = safe_get(face, "geometry")
    return _surface_labels().get(safe_get(geometry, "surfaceType"), "unknown")


def _counts(entity, collection_name):
    """The size of one of an entity's BRep collections, zero when absent."""
    return safe_get(safe_get(entity, collection_name), "count", 0)


def _body_summary(body):
    """One body as the list_bodies response reports it."""
    return {
        "name": safe_get(body, "name"),
        "is_solid": bool(safe_get(body, "isSolid", True)),
        "volume_cm3": safe_get(body, "volume"),
        "area_cm2": safe_get(body, "area"),
        "bounding_box": _box_dict(body),
        "faces_count": _counts(body, "faces"),
        "edges_count": _counts(body, "edges"),
        "entity_token": safe_get(body, "entityToken"),
    }


def _face_summary(face):
    """One face as inspect_entity reports it."""
    return {
        "name": safe_get(face, "name"),
        "area_cm2": safe_get(face, "area"),
        "centroid": _point_dict(safe_get(face, "centroid")),
        "bounding_box": _box_dict(face),
        "surface_kind": _surface_kind(face),
        "entity_token": safe_get(face, "entityToken"),
    }


def _edge_summary(edge):
    """One edge as inspect_entity reports it."""
    return {
        "name": safe_get(edge, "name"),
        "length_cm": safe_get(edge, "length"),
        "bounding_box": _box_dict(edge),
        "entity_token": safe_get(edge, "entityToken"),
    }


def _timeline_node(node, position):
    """One timeline entry as list_features reports it.

    The timeline holds sketches, construction geometry, canvas and decal
    inserts, joints, and PMI alongside features, so ``kind`` says which.
    ``index`` is read from the node and falls back to the position in the
    collection; a TimelineGroup publishes -1.
    """
    health = _health_labels().get(safe_get(node, "healthState"), "unknown")
    # errorOrWarningMessage is only populated for a warning or an error; reading
    # it unconditionally reports a stale message for a healthy node.
    message = ""
    if health in ("warning", "error"):
        message = safe_get(node, "errorOrWarningMessage") or ""
    return {
        "name": safe_get(node, "name"),
        "index": safe_get(node, "index", position),
        "is_suppressed": bool(safe_get(node, "isSuppressed", False)),
        "health": health,
        "error_or_warning_message": message,
        "kind": _entity_kind(node),
    }


def _is_planar_face(entity):
    return _entity_kind(entity) == _FACE_KIND and _surface_kind(entity) == "plane"


def _angle_compatible(entity):
    """Whether measureAngle can use this entity.

    Angle accepts points, linear edges, axes, and planar faces.  A body is a
    volume with no single direction, and a curved face has no plane to measure
    against, so both are rejected -- the API does the same, only by raising.
    """
    kind = _entity_kind(entity)
    if kind == _BODY_KIND:
        return False
    if kind == _FACE_KIND:
        return _surface_kind(entity) == "plane"
    return True


def _check_measure_kinds(mode, one, two):
    """Pre-validate entity kinds for a measurement mode, or None to proceed."""
    if mode != "angle":
        return None
    incompatible = [
        label for label, entity in (("entity_one", one), ("entity_two", two)) if not _angle_compatible(entity)
    ]
    if incompatible:
        return structured_error(
            "invalid_value",
            "measureAngle accepts points, linear edges, axes, and planar faces; "
            "a body or a curved face has no single direction to measure. "
            f"Incompatible argument(s): {', '.join(incompatible)}",
            "Re-select geometry of an angle-compatible kind, or call measure with mode 'distance'.",
        )
    return None


@map_tool_errors
def list_bodies(arguments):
    """List every solid and surface body in the root component.

    Each entry reports the body's name, whether it is solid, its volume in cubic
    centimetres, its surface area in square centimetres, its tight-fitting
    bounding box, and its face and edge counts.  A design with no bodies returns
    an empty list -- that is a valid state to inspect, not an error.
    """
    del arguments
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    bodies = safe_get(safe_get(design, "rootComponent"), "bodies")
    if bodies is None:
        return structured_error(
            "unsupported_operation",
            "This Fusion build exposes no body collection on the root component",
        )
    count = safe_get(bodies, "count", 0)
    return success_result(
        {
            "count": count,
            "bodies": [_body_summary(bodies.item(index)) for index in range(count)],
        }
    )


@map_tool_errors
def inspect_entity(arguments):
    """Report the geometry of one body, face, or edge by stored handle.

    The reported fields depend on the kind, discriminated by ``objectType``: a
    body reports volume, area, bounding box, and its face and edge counts; a face
    reports area, centroid, bounding box, and its surface kind (plane, cylinder,
    cone, sphere, torus, or one of the two elliptical or nurbs kinds); an edge
    reports its length and bounding box.  An entity of any other kind is an
    ``invalid_value`` rather than a best-effort guess.
    """
    entity_ref = require(arguments, "entity")["entity"]
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    entity = _resolve_entity(entity_ref, design)
    kind = _entity_kind(entity)
    if kind == _BODY_KIND:
        summary = _body_summary(entity)
    elif kind == _FACE_KIND:
        summary = _face_summary(entity)
    elif kind == _EDGE_KIND:
        summary = _edge_summary(entity)
    else:
        return structured_error(
            "invalid_value",
            f"inspect_entity measures bodies, faces, and edges; '{kind}' is none of those",
            "Select a body, face, or edge, then call get_active_selection to refresh the handle.",
        )
    return success_result({"entity": entity_ref, "kind": kind.split(".")[-1], **summary})


@map_tool_errors
def list_features(arguments):
    """List the design's timeline: every node, not only feature nodes.

    The timeline holds sketches, construction geometry, canvas and decal inserts,
    joints, and PMI alongside the features a model is built from, so every node
    is listed and each carries its ``kind``.  Each reports its name, timeline
    index, suppression flag, health label (healthy, warning, error, suppressed,
    rolled back, or unknown), and the message Fusion attaches to a warning or an
    error.  A direct design has no timeline at all and reports an empty list.
    """
    del arguments
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    timeline = safe_get(design, "timeline")
    if timeline is None:
        # Direct modelling has no timeline; that is a valid empty state.
        return success_result({"count": 0, "features": []})
    count = safe_get(timeline, "count", 0)
    return success_result(
        {
            "count": count,
            "features": [_timeline_node(timeline.item(index), index) for index in range(count)],
        }
    )


@map_tool_errors
def measure(arguments):
    """Measure between two stored entities: minimum distance or angle.

    ``mode`` is ``distance`` (the default) or ``angle``.  Distance reports the
    minimum gap in centimetres; angle reports the value in radians *and* degrees.
    The two APIs accept different entity kinds -- distance takes bodies, faces,
    edges, and points, while angle rejects bodies and curved faces -- so the
    kinds are validated for the requested mode and an incompatible argument is
    reported as ``invalid_value`` before Fusion is asked to measure it.
    """
    entity_one_ref = require(arguments, "entity_one")["entity_one"]
    entity_two_ref = require(arguments, "entity_two")["entity_two"]
    mode = arguments.get("mode", "distance")
    if mode not in _MEASURE_MODES:
        raise ValueError("mode must be 'distance' or 'angle'")
    design = active_design()
    if design is None:
        return structured_error("no_active_document", _NO_DESIGN)
    one = _resolve_entity(entity_one_ref, design)
    two = _resolve_entity(entity_two_ref, design)
    kind_error = _check_measure_kinds(mode, one, two)
    if kind_error is not None:
        return kind_error
    manager = safe_get(active_app(), "measureManager")
    if manager is None:
        return structured_error(
            "unsupported_operation",
            "This Fusion build exposes no measure manager",
        )
    results = manager.measureMinimumDistance(one, two) if mode == "distance" else manager.measureAngle(one, two)
    if results is None or not safe_get(results, "isValid", True):
        return structured_error(
            "invalid_value",
            "Fusion could not measure those two entities; check the geometry is still in the design",
        )
    payload = {
        "mode": mode,
        "entity_one": entity_one_ref,
        "entity_two": entity_two_ref,
        "is_valid": bool(safe_get(results, "isValid", True)),
        "position_one": _point_dict(safe_get(results, "positionOne")),
        "position_two": _point_dict(safe_get(results, "positionTwo")),
    }
    if mode == "distance":
        payload["distance_cm"] = safe_get(results, "value")
    else:
        radians = safe_get(results, "value")
        payload["angle_rad"] = radians
        payload["angle_deg"] = math.degrees(radians) if radians is not None else None
        payload["position_three"] = _point_dict(safe_get(results, "positionThree"))
    return success_result(payload)
