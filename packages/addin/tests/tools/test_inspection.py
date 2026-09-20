"""Inspection tool tests against the behavioral fake: list_bodies, inspect_entity,
list_features, and measure.

The four tools are read-only, so every test drives the same round trip a caller
makes and asserts what came back without changing the design.  Geometry is
addressed by stored selection handle, so a test puts an entity in the selection
set (as a user picking it would), calls ``get_active_selection`` to store it as
``$selection_N``, then hands that handle to the tool.

The interesting parts are the contracts the handlers enforce themselves: the
per-kind discrimination in inspect_entity, the full surface-type and health-state
maps, the empty states that are answers rather than errors, and the measure
angle/distance kind asymmetry -- angle rejects a body and a curved face *before*
the API is ever asked to measure them.
"""

import math

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)
import pytest
from fake_fusion import values
from fake_fusion.design import FakeDesign
from fake_fusion.features import (
    FakeBRepEdge,
    FakeBRepFace,
    FakeMeasureResults,
    FakeSurface,
    FakeTimelineObject,
)

# ── Helpers ─────────────────────────────────────────────────────────────────────


def _select(call):
    """Store the current selection set, as a caller must before addressing geometry."""
    return call("get_active_selection")


def _handle(fusion, call, *entities):
    """Clear the selection set, pick exactly ``entities``, and store them.

    Returns the handles in order, so a test addresses the very objects it built
    regardless of what earlier helpers left selected.
    """
    selections = fusion.app.userInterface.activeSelections
    selections.clear()
    for entity in entities:
        selections.add(entity)
    _select(call)
    return [f"$selection_{index}" for index in range(len(entities))]


class _TypedFace(FakeBRepFace):
    """A face whose geometry reports one specific ``SurfaceTypes`` member.

    The stock fake only distinguishes planar from nurbs; mapping all eight
    published kinds needs a face that carries an arbitrary surface type.
    """

    def __init__(self, surface_type, name="TypedFace", area=1.0):
        super().__init__(name, area=area)
        self._surface_type = surface_type

    @property
    def geometry(self):
        return FakeSurface(self._surface_type)


_SURFACE_LABELS = {
    values.SurfaceTypes.PlaneSurfaceType: "plane",
    values.SurfaceTypes.CylinderSurfaceType: "cylinder",
    values.SurfaceTypes.ConeSurfaceType: "cone",
    values.SurfaceTypes.SphereSurfaceType: "sphere",
    values.SurfaceTypes.TorusSurfaceType: "torus",
    values.SurfaceTypes.EllipticalCylinderSurfaceType: "elliptical_cylinder",
    values.SurfaceTypes.EllipticalConeSurfaceType: "elliptical_cone",
    values.SurfaceTypes.NurbsSurfaceType: "nurbs",
}

_HEALTH_LABELS = {
    values.FeatureHealthStates.HealthyFeatureHealthState: "healthy",
    values.FeatureHealthStates.WarningFeatureHealthState: "warning",
    values.FeatureHealthStates.ErrorFeatureHealthState: "error",
    values.FeatureHealthStates.SuppressedFeatureHealthState: "suppressed",
    values.FeatureHealthStates.RolledBackFeatureHealthState: "rolled_back",
    values.FeatureHealthStates.UnknownFeatureHealthState: "unknown",
}


def _must_not_be_called(*args, **kwargs):
    raise AssertionError("the measure API must not be reached for incompatible kinds")


# ── list_bodies ────────────────────────────────────────────────────────────────


def test_list_bodies_reports_every_body_in_the_root_component(fusion, call, mcp):
    fusion.new_document("Bracket")
    fusion.add_body("Base", shape="box", length=2.0, width=2.0, height=2.0, select=False)
    fusion.add_body("Pin", shape="cylinder", height=1.0, radius=0.5, select=False)

    payload = mcp.ok(call("list_bodies"))

    assert payload["count"] == 2
    base, pin = payload["bodies"]
    assert base["name"] == "Base"
    assert base["is_solid"] is True
    assert base["volume_cm3"] == 8.0  # 2 x 2 x 2
    assert base["area_cm2"] == 24.0  # 2(lw + lh + wh)
    assert base["bounding_box"] == {
        "min": {"x": 0.0, "y": 0.0, "z": 0.0},
        "max": {"x": 2.0, "y": 2.0, "z": 2.0},
    }
    assert base["entity_token"] == "body:Base"
    assert isinstance(base["faces_count"], int)
    assert isinstance(base["edges_count"], int)
    assert pin["name"] == "Pin"
    assert pin["volume_cm3"] > 0.0


def test_list_bodies_on_an_empty_design_returns_an_empty_list_not_an_error(fusion, call, mcp):
    fusion.new_document("Empty")

    payload = mcp.ok(call("list_bodies"))

    assert payload == {"count": 0, "bodies": []}


def test_list_bodies_without_an_active_design(fusion_empty, call, mcp):
    assert mcp.error_kind(call("list_bodies")) == "no_active_document"


def test_list_bodies_reports_a_build_without_a_body_collection(fusion, call, mcp, monkeypatch):
    class _BareComponent:
        name = "Root"

    monkeypatch.setattr(FakeDesign, "rootComponent", property(lambda self: _BareComponent()))

    assert mcp.error_kind(call("list_bodies")) == "unsupported_operation"


# ── inspect_entity: happy paths and per-kind discrimination ─────────────────────


def test_inspect_entity_reports_a_body(fusion, call, mcp):
    fusion.new_document("Bracket")
    fusion.add_body("Base", shape="box", length=2.0, width=2.0, height=2.0, select=False)
    (handle,) = _handle(fusion, call, fusion.root.bodies.item(0))

    payload = mcp.ok(call("inspect_entity", entity=handle))

    assert payload["entity"] == handle
    assert payload["kind"] == "BRepBody"
    assert payload["name"] == "Base"
    assert payload["is_solid"] is True
    assert payload["volume_cm3"] == 8.0
    assert payload["area_cm2"] == 24.0
    assert payload["bounding_box"]["max"] == {"x": 2.0, "y": 2.0, "z": 2.0}
    assert payload["entity_token"] == "body:Base"


def test_inspect_entity_reports_a_face(fusion, call, mcp):
    fusion.new_document("Bracket")
    face = FakeBRepFace("Top", area=4.0)
    (handle,) = _handle(fusion, call, face)

    payload = mcp.ok(call("inspect_entity", entity=handle))

    assert payload["kind"] == "BRepFace"
    assert payload["name"] == "Top"
    assert payload["area_cm2"] == 4.0
    assert payload["centroid"] == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert payload["surface_kind"] == "plane"
    assert payload["entity_token"] == "face:Top"


def test_inspect_entity_reports_an_edge(fusion, call, mcp):
    fusion.new_document("Bracket")
    (handle,) = _handle(fusion, call, FakeBRepEdge("Margin", 10.0))

    payload = mcp.ok(call("inspect_entity", entity=handle))

    assert payload["kind"] == "BRepEdge"
    assert payload["name"] == "Margin"
    assert payload["length_cm"] == 10.0
    assert payload["bounding_box"] == {
        "min": {"x": 0.0, "y": 0.0, "z": 0.0},
        "max": {"x": 10.0, "y": 0.0, "z": 0.0},
    }
    assert payload["entity_token"] == "edge:Margin"


def test_inspect_entity_reports_the_kind_of_the_resolved_object_not_the_handle(fusion, call, mcp):
    fusion.new_document("Bracket")
    face = FakeBRepFace("Top", area=4.0)
    handle, _ = _handle(fusion, call, face, FakeBRepEdge("Margin", 10.0))

    payload = mcp.ok(call("inspect_entity", entity=handle))

    assert payload["kind"] == "BRepFace"
    assert payload["entity"] == handle


@pytest.mark.parametrize("surface_type, expected", sorted(_SURFACE_LABELS.items()))
def test_inspect_entity_maps_every_published_surface_type(fusion, call, mcp, surface_type, expected):
    fusion.new_document("Bracket")
    (handle,) = _handle(fusion, call, _TypedFace(surface_type))

    payload = mcp.ok(call("inspect_entity", entity=handle))

    assert payload["surface_kind"] == expected


@pytest.mark.parametrize(
    "surface_type",
    [999, None],
    ids=["unpublished-member", "no-surface-type-at-all"],
)
def test_inspect_entity_reports_unknown_for_a_surface_type_it_does_not_map(fusion, call, mcp, surface_type):
    fusion.new_document("Bracket")
    (handle,) = _handle(fusion, call, _TypedFace(surface_type))

    payload = mcp.ok(call("inspect_entity", entity=handle))

    assert payload["surface_kind"] == "unknown"


def test_inspect_entity_rejects_a_kind_it_does_not_inspect(fusion, call, mcp):
    fusion.new_document("Bracket")
    (handle,) = _handle(fusion, call, FakeTimelineObject("PinSketch", "Sketch"))

    message = mcp.error(call("inspect_entity", entity=handle))

    assert mcp.error_kind(call("inspect_entity", entity=handle)) == "invalid_value"
    assert "bodies, faces, and edges" in message


def test_inspect_entity_requires_an_entity_argument(fusion, call, mcp):
    fusion.new_document("Bracket")

    assert mcp.error_kind(call("inspect_entity")) == "missing_argument"


def test_inspect_entity_rejects_a_handle_that_is_not_in_the_store(fusion, call, mcp):
    fusion.new_document("Bracket")

    assert mcp.error_kind(call("inspect_entity", entity="$selection_404")) == "invalid_value"


def test_inspect_entity_without_an_active_design(fusion_empty, call, mcp):
    assert mcp.error_kind(call("inspect_entity", entity="$selection_0")) == "no_active_document"


# ── list_features ───────────────────────────────────────────────────────────────


def test_list_features_reports_every_timeline_node(fusion, call, mcp):
    fusion.new_document("Bracket")
    fusion.add_timeline_node("FloorSketch", "Sketch")
    fusion.add_timeline_node(
        "RigidJoint",
        "Joint",
        health=values.FeatureHealthStates.WarningFeatureHealthState,
        message="degrees of freedom remain",
    )

    payload = mcp.ok(call("list_features"))

    assert payload["count"] == 2
    sketch, joint = payload["features"]
    assert sketch["name"] == "FloorSketch"
    assert sketch["index"] == 0
    assert sketch["is_suppressed"] is False
    assert sketch["health"] == "healthy"
    assert sketch["error_or_warning_message"] == ""  # a healthy node carries no message
    assert sketch["kind"] == "adsk.fusion.Sketch"
    assert joint["name"] == "RigidJoint"
    assert joint["index"] == 1
    assert joint["health"] == "warning"
    assert joint["error_or_warning_message"] == "degrees of freedom remain"
    assert joint["kind"] == "adsk.fusion.Joint"


@pytest.mark.parametrize("health_state, expected", sorted(_HEALTH_LABELS.items()))
def test_list_features_maps_every_health_state(fusion, call, mcp, health_state, expected):
    fusion.new_document("Bracket")
    fusion.add_timeline_node("Node", "Sketch", health=health_state, message="detail")

    payload = mcp.ok(call("list_features"))

    assert payload["features"][0]["health"] == expected


@pytest.mark.parametrize(
    "health_state",
    [
        values.FeatureHealthStates.HealthyFeatureHealthState,
        values.FeatureHealthStates.SuppressedFeatureHealthState,
        values.FeatureHealthStates.RolledBackFeatureHealthState,
        values.FeatureHealthStates.UnknownFeatureHealthState,
    ],
)
def test_list_features_reads_the_message_only_for_a_warning_or_an_error(fusion, call, mcp, health_state):
    fusion.new_document("Bracket")
    fusion.add_timeline_node("Node", "Sketch", health=health_state, message="stale detail")

    payload = mcp.ok(call("list_features"))

    # errorOrWarningMessage is only populated on a warning or an error, so a
    # healthy-looking node never reports a stale message.
    assert payload["features"][0]["error_or_warning_message"] == ""


def test_list_features_on_a_direct_design_reports_an_empty_timeline(fusion, call, mcp):
    fusion.new_document("Direct", design_type="direct")

    # The premise of the guard: a direct design has no timeline object at all.
    assert fusion.design.timeline is None

    payload = mcp.ok(call("list_features"))

    assert payload == {"count": 0, "features": []}


def test_list_features_without_an_active_design(fusion_empty, call, mcp):
    assert mcp.error_kind(call("list_features")) == "no_active_document"


# ── measure: distance ──────────────────────────────────────────────────────────


def test_measure_distance_reports_the_minimum_gap(fusion, call, mcp):
    fusion.new_document("Bracket")
    near = FakeBRepEdge("Near", 1.0, start=values.Point3D.create(), end=values.Point3D.create(1.0, 0.0, 0.0))
    far = FakeBRepEdge("Far", 1.0, start=values.Point3D.create(5.0, 0.0, 0.0), end=values.Point3D.create(6.0, 0.0, 0.0))
    one, two = _handle(fusion, call, near, far)

    payload = mcp.ok(call("measure", entity_one=one, entity_two=two))

    assert payload["mode"] == "distance"
    assert payload["entity_one"] == one
    assert payload["entity_two"] == two
    assert payload["distance_cm"] == 4.0
    assert payload["is_valid"] is True
    assert payload["position_one"] is not None
    assert payload["position_two"] is not None


def test_measure_distance_is_the_default_mode(fusion, call, mcp):
    fusion.new_document("Bracket")
    near = FakeBRepEdge("Near", 1.0)
    far = FakeBRepEdge("Far", 1.0, start=values.Point3D.create(5.0, 0.0, 0.0), end=values.Point3D.create(6.0, 0.0, 0.0))
    one, two = _handle(fusion, call, near, far)

    payload = mcp.ok(call("measure", entity_one=one, entity_two=two))

    assert payload["mode"] == "distance"
    assert "distance_cm" in payload
    assert "angle_rad" not in payload


def test_measure_distance_accepts_a_body(fusion, call, mcp):
    fusion.new_document("Bracket")
    fusion.add_body("Base", shape="box", length=2.0, width=2.0, height=2.0, select=False)
    edge = FakeBRepEdge(
        "Far", 1.0, start=values.Point3D.create(5.0, 0.0, 0.0), end=values.Point3D.create(6.0, 0.0, 0.0)
    )
    one, two = _handle(fusion, call, fusion.root.bodies.item(0), edge)

    payload = mcp.ok(call("measure", entity_one=one, entity_two=two, mode="distance"))

    assert payload["mode"] == "distance"
    assert payload["distance_cm"] == 3.0  # 5.0 minus the box's 2.0 extent


# ── measure: angle ─────────────────────────────────────────────────────────────


def test_measure_angle_converts_radians_to_degrees(fusion, call, mcp):
    fusion.new_document("Bracket")
    x_axis = FakeBRepEdge("X", 1.0, start=values.Point3D.create(), end=values.Point3D.create(1.0, 0.0, 0.0))
    y_axis = FakeBRepEdge("Y", 1.0, start=values.Point3D.create(), end=values.Point3D.create(0.0, 1.0, 0.0))
    one, two = _handle(fusion, call, x_axis, y_axis)

    payload = mcp.ok(call("measure", entity_one=one, entity_two=two, mode="angle"))

    assert payload["mode"] == "angle"
    assert payload["angle_rad"] == pytest.approx(math.pi / 2.0)
    assert payload["angle_deg"] == pytest.approx(90.0)


def test_measure_angle_reports_position_three_and_distance_does_not(fusion, call, mcp):
    fusion.new_document("Bracket")
    x_axis = FakeBRepEdge("X", 1.0, start=values.Point3D.create(), end=values.Point3D.create(1.0, 0.0, 0.0))
    y_axis = FakeBRepEdge("Y", 1.0, start=values.Point3D.create(), end=values.Point3D.create(0.0, 1.0, 0.0))
    one, two = _handle(fusion, call, x_axis, y_axis)

    angle = mcp.ok(call("measure", entity_one=one, entity_two=two, mode="angle"))
    distance = mcp.ok(call("measure", entity_one=one, entity_two=two))

    assert "position_three" in angle
    assert "position_three" not in distance


def test_measure_angle_accepts_a_planar_face_and_an_edge(fusion, call, mcp):
    fusion.new_document("Bracket")
    planar = FakeBRepFace("Floor", area=1.0, is_planar=True)
    x_axis = FakeBRepEdge("X", 1.0, start=values.Point3D.create(), end=values.Point3D.create(1.0, 0.0, 0.0))
    one, two = _handle(fusion, call, planar, x_axis)

    payload = mcp.ok(call("measure", entity_one=one, entity_two=two, mode="angle"))

    # The fake's planar normal is +z, perpendicular to the edge along +x.
    assert payload["angle_deg"] == pytest.approx(90.0)


def test_measure_angle_rejects_a_body_before_the_api_is_called(fusion, call, mcp, monkeypatch):
    fusion.new_document("Bracket")
    fusion.add_body("Base", shape="box", length=2.0, width=2.0, height=2.0, select=False)
    edge = FakeBRepEdge("X", 1.0)
    one, two = _handle(fusion, call, fusion.root.bodies.item(0), edge)
    monkeypatch.setattr(fusion.app.measureManager, "measureAngle", _must_not_be_called)

    message = mcp.error(call("measure", entity_one=one, entity_two=two, mode="angle"))

    assert mcp.error_kind(call("measure", entity_one=one, entity_two=two, mode="angle")) == "invalid_value"
    assert "no single direction" in message


def test_measure_angle_rejects_a_curved_face_before_the_api_is_called(fusion, call, mcp, monkeypatch):
    fusion.new_document("Bracket")
    curved = FakeBRepFace("Sleeve", area=1.0, is_planar=False)
    edge = FakeBRepEdge("X", 1.0)
    one, two = _handle(fusion, call, curved, edge)
    monkeypatch.setattr(fusion.app.measureManager, "measureAngle", _must_not_be_called)

    assert mcp.error_kind(call("measure", entity_one=one, entity_two=two, mode="angle")) == "invalid_value"


def test_measure_angle_reports_both_incompatible_arguments(fusion, call, mcp, monkeypatch):
    fusion.new_document("Bracket")
    fusion.add_body("Base", shape="box", length=2.0, width=2.0, height=2.0, select=False)
    curved = FakeBRepFace("Sleeve", area=1.0, is_planar=False)
    one, two = _handle(fusion, call, fusion.root.bodies.item(0), curved)
    monkeypatch.setattr(fusion.app.measureManager, "measureAngle", _must_not_be_called)

    message = mcp.error(call("measure", entity_one=one, entity_two=two, mode="angle"))

    assert "entity_one" in message
    assert "entity_two" in message


# ── measure: shared failure modes ───────────────────────────────────────────────


def test_measure_rejects_an_unknown_mode(fusion, call, mcp):
    fusion.new_document("Bracket")
    one, two = _handle(fusion, call, FakeBRepEdge("A", 1.0), FakeBRepEdge("B", 1.0))

    assert mcp.error_kind(call("measure", entity_one=one, entity_two=two, mode="diagonal")) == "invalid_value"


def test_measure_requires_both_entities(fusion, call, mcp):
    fusion.new_document("Bracket")

    assert mcp.error_kind(call("measure", entity_one="$selection_0")) == "missing_argument"


def test_measure_without_an_active_design(fusion_empty, call, mcp):
    assert mcp.error_kind(call("measure", entity_one="$selection_0", entity_two="$selection_1")) == "no_active_document"


def test_measure_reports_an_unmeasurable_pair_as_invalid(fusion, call, mcp, monkeypatch):
    fusion.new_document("Bracket")
    one, two = _handle(fusion, call, FakeBRepEdge("A", 1.0), FakeBRepEdge("B", 1.0))
    monkeypatch.setattr(
        fusion.app.measureManager,
        "measureMinimumDistance",
        lambda *args, **kwargs: FakeMeasureResults(None, is_valid=False),
    )

    assert mcp.error_kind(call("measure", entity_one=one, entity_two=two)) == "invalid_value"
