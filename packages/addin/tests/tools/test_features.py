"""Feature tool tests against the behavioral fake: fillet, chamfer, hole, and
the two pattern tools.

Every test drives the same two-step round trip a real caller makes, because
that is the only path the tools accept: put an entity in the selection set (as
a user clicking it would), call ``get_active_selection`` to store it as
``$selection_N``, then hand that handle to the feature tool.  The handle is
resolved back to the very object that was picked, so a test that fakes a
handle never gets to pass.

The fake does not simulate geometric side effects: a built feature records the
parameters that produced it and round-trips them to the caller.  What *is*
real is the validation, so these tests cover both -- what the tool reported,
and what the fake recorded -- and never assert a rounded edge an offline fake
cannot compute.
"""

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)
from fake_fusion import values
from fake_fusion.design import FakeComponent
from fake_fusion.features import FakeMaterialLibraries, FakeMaterialLibrary


def _last_feature(fusion):
    """The most recent timeline entry, built by the tool under test."""
    return list(fusion.design.rootComponent.features)[-1]


def _select(call):
    """Store the current selection set, as a caller must before addressing geometry."""
    return call("get_active_selection")


# ── Fillet ────────────────────────────────────────────────────────────────────


def test_fillet_round_trips_a_stored_edge_handle(fusion, call, mcp):
    fusion.add_edge("BracketTop", 10.0)
    fusion.add_edge("BracketBottom", 10.0)
    _select(call)

    payload = mcp.ok(
        call(
            "fillet",
            edges=["$selection_0", "$selection_1"],
            radius="5 mm",
        )
    )
    assert payload["feature_type"] == "Fillet"
    assert payload["edge_count"] == 2
    assert payload["radius"] == "5 mm"
    assert payload["is_tangent_chain"] is True
    # The fake recorded the resolved dimension, not the expression string.
    assert _last_feature(fusion).params["radius_cm"] == 0.5


def test_fillet_accepts_a_bare_centimetre_radius(fusion, call, mcp):
    fusion.add_edge("Edge", 10.0)
    _select(call)

    payload = mcp.ok(call("fillet", edges=["$selection_0"], radius=0.5))
    assert payload["radius"] == 0.5
    assert _last_feature(fusion).params["radius_cm"] == 0.5


def test_fillet_honours_the_tangent_chain_flag(fusion, call, mcp):
    fusion.add_edge("Edge", 10.0)
    _select(call)

    payload = mcp.ok(call("fillet", edges=["$selection_0"], radius="5 mm", is_tangent_chain=False))
    assert payload["is_tangent_chain"] is False
    assert _last_feature(fusion).params["is_tangent_chain"] is False


def test_fillet_needs_an_active_design(fusion_empty, call, mcp):
    assert mcp.error_kind(call("fillet", edges=["$selection_0"], radius="5 mm")) == ("no_active_document")


def test_fillet_requires_at_least_one_edge(fusion, call, mcp):
    message = mcp.error(call("fillet", edges=[], radius="5 mm"))
    assert "missing required argument" in message


def test_fillet_rejects_a_non_positive_radius(fusion, call, mcp):
    fusion.add_edge("Edge", 10.0)
    _select(call)

    assert "radius must be greater than zero" in mcp.error(call("fillet", edges=["$selection_0"], radius="0 mm"))
    assert "radius must be greater than zero" in mcp.error(call("fillet", edges=["$selection_0"], radius=-1))


def test_fillet_reports_a_radius_that_does_not_fit_the_edge(fusion, call, mcp):
    # A 1 cm edge cannot carry a 2 cm radius; real Fusion reports that by
    # returning None from add(), which the tool surfaces as invalid_value.
    fusion.add_edge("ShortEdge", 1.0)
    _select(call)

    assert mcp.error_kind(call("fillet", edges=["$selection_0"], radius="20 mm")) == "invalid_value"


def test_fillet_rejects_a_non_boolean_tangent_chain(fusion, call, mcp):
    fusion.add_edge("Edge", 10.0)
    _select(call)

    assert (
        mcp.error_kind(
            call(
                "fillet",
                edges=["$selection_0"],
                radius="5 mm",
                is_tangent_chain="yes",
            )
        )
        == "invalid_value"
    )


# ── Chamfer ───────────────────────────────────────────────────────────────────


def test_chamfer_builds_an_equal_distance_set(fusion, call, mcp):
    fusion.add_edge("Edge", 10.0)
    _select(call)

    payload = mcp.ok(call("chamfer", edges=["$selection_0"], distance="2 mm"))
    assert payload["feature_type"] == "Chamfer"
    assert payload["edge_count"] == 1
    assert payload["distance"] == "2 mm"
    assert _last_feature(fusion).params["distance_cm"] == 0.2


def test_chamfer_needs_an_active_design(fusion_empty, call, mcp):
    assert mcp.error_kind(call("chamfer", edges=["$selection_0"], distance="2 mm")) == ("no_active_document")


def test_chamfer_requires_edges_and_a_distance(fusion, call, mcp):
    assert "missing required argument" in mcp.error(call("chamfer", edges=[], distance="2 mm"))
    assert "missing required argument" in mcp.error(call("chamfer", edges=["$selection_0"]))


def test_chamfer_rejects_a_non_positive_distance(fusion, call, mcp):
    fusion.add_edge("Edge", 10.0)
    _select(call)

    assert "distance must be greater than zero" in mcp.error(call("chamfer", edges=["$selection_0"], distance="0 mm"))
    assert "distance must be greater than zero" in mcp.error(call("chamfer", edges=["$selection_0"], distance=0))


# ── Hole ──────────────────────────────────────────────────────────────────────


def test_hole_drills_to_a_distance_depth(fusion, call, mcp):
    fusion.add_face("TopFace", area=4.0)
    _select(call)

    payload = mcp.ok(
        call(
            "hole",
            face="$selection_0",
            position={"x": 0, "y": 0, "z": 0},
            diameter="8 mm",
            extent="distance",
            depth="10 mm",
        )
    )
    assert payload["feature_type"] == "Hole"
    assert payload["diameter"] == "8 mm"
    assert payload["extent"] == "distance"
    assert payload["depth"] == "10 mm"
    assert payload["direction"] == "positive"
    built = _last_feature(fusion)
    assert built.params["diameter_cm"] == 0.8
    assert built.params["depth_cm"] == 1.0


def test_hole_runs_through_all_in_either_direction(fusion, call, mcp):
    fusion.add_face("TopFace", area=4.0)
    _select(call)

    payload = mcp.ok(
        call(
            "hole",
            face="$selection_0",
            position={"x": 0, "y": 0, "z": 0},
            diameter="8 mm",
            extent="through_all",
            direction="negative",
        )
    )
    assert payload["extent"] == "through_all"
    assert payload["depth"] is None
    assert payload["direction"] == "negative"
    assert _last_feature(fusion).params["extent"] == "all"


def test_hole_needs_an_active_design(fusion_empty, call, mcp):
    assert (
        mcp.error_kind(
            call(
                "hole",
                face="$selection_0",
                position={"x": 0, "y": 0, "z": 0},
                diameter="8 mm",
            )
        )
        == "no_active_document"
    )


def test_hole_requires_face_position_and_diameter(fusion, call, mcp):
    fusion.add_face("TopFace", area=4.0)
    _select(call)

    assert "missing required argument" in mcp.error(
        call(
            "hole",
            position={"x": 0, "y": 0, "z": 0},
            diameter="8 mm",
        )
    )
    assert "missing required argument" in mcp.error(
        call(
            "hole",
            face="$selection_0",
            diameter="8 mm",
        )
    )
    assert "missing required argument" in mcp.error(
        call(
            "hole",
            face="$selection_0",
            position={},
            diameter="8 mm",
        )
    )


def test_hole_rejects_a_non_positive_diameter(fusion, call, mcp):
    fusion.add_face("TopFace", area=4.0)
    _select(call)

    assert "diameter must be greater than zero" in mcp.error(
        call(
            "hole",
            face="$selection_0",
            position={"x": 0, "y": 0, "z": 0},
            diameter="0 mm",
            extent="through_all",
        )
    )
    assert "diameter must be greater than zero" in mcp.error(
        call(
            "hole",
            face="$selection_0",
            position={"x": 0, "y": 0, "z": 0},
            diameter=0,
            extent="through_all",
        )
    )


def test_hole_rejects_a_non_positive_depth(fusion, call, mcp):
    fusion.add_face("TopFace", area=4.0)
    _select(call)

    assert "depth must be greater than zero" in mcp.error(
        call(
            "hole",
            face="$selection_0",
            position={"x": 0, "y": 0, "z": 0},
            diameter="8 mm",
            extent="distance",
            depth="0 mm",
        )
    )


def test_hole_distance_extent_requires_a_depth(fusion, call, mcp):
    fusion.add_face("TopFace", area=4.0)
    _select(call)

    assert "depth is required when extent is 'distance'" in mcp.error(
        call(
            "hole",
            face="$selection_0",
            position={"x": 0, "y": 0, "z": 0},
            diameter="8 mm",
        )
    )
    assert "depth is required when extent is 'distance'" in mcp.error(
        call(
            "hole",
            face="$selection_0",
            position={"x": 0, "y": 0, "z": 0},
            diameter="8 mm",
            extent="distance",
        )
    )


def test_hole_rejects_an_unknown_extent_or_direction(fusion, call, mcp):
    fusion.add_face("TopFace", area=4.0)
    _select(call)

    assert "extent must be 'distance' or 'through_all'" in mcp.error(
        call(
            "hole",
            face="$selection_0",
            position={"x": 0, "y": 0, "z": 0},
            diameter="8 mm",
            extent="to_the_moon",
        )
    )
    assert "direction must be 'positive' or 'negative'" in mcp.error(
        call(
            "hole",
            face="$selection_0",
            position={"x": 0, "y": 0, "z": 0},
            diameter="8 mm",
            extent="through_all",
            direction="sideways",
        )
    )


def test_hole_requires_a_planar_face(fusion, call, mcp):
    fusion.add_face("CurvedFace", area=4.0, is_planar=False)
    _select(call)

    assert "planar face" in mcp.error(
        call(
            "hole",
            face="$selection_0",
            position={"x": 0, "y": 0, "z": 0},
            diameter="8 mm",
            extent="through_all",
        )
    )


def test_hole_rejects_a_position_that_is_not_a_point(fusion, call, mcp):
    fusion.add_face("TopFace", area=4.0)
    _select(call)

    assert "position must be an object with numeric x, y, and z" in mcp.error(
        call(
            "hole",
            face="$selection_0",
            position={"x": "wide", "y": 0, "z": 0},
            diameter="8 mm",
            extent="through_all",
        )
    )


# ── Rectangular pattern ──────────────────────────────────────────────────────


def test_rectangular_pattern_along_one_direction(fusion, call, mcp):
    fusion.add_edge("Seed1", 10.0)
    fusion.add_edge("Seed2", 10.0)
    fusion.add_edge("Axis", 20.0)
    _select(call)

    payload = mcp.ok(
        call(
            "rectangular_pattern",
            entities=["$selection_0", "$selection_1"],
            direction_one="$selection_2",
            quantity_one=3,
            distance_one="20 mm",
        )
    )
    assert payload["feature_type"] == "RectangularPattern"
    assert payload["entity_count"] == 2
    assert payload["quantity_one"] == 3
    assert payload["quantity_two"] is None
    assert payload["is_symmetric"] is False
    built = _last_feature(fusion)
    assert built.params["quantity_one"] == 3
    assert built.params["quantity_two"] is None


def test_rectangular_pattern_in_two_symmetric_directions(fusion, call, mcp):
    fusion.add_edge("Seed", 10.0)
    fusion.add_edge("AxisX", 20.0)
    fusion.add_edge("AxisY", 20.0)
    _select(call)

    payload = mcp.ok(
        call(
            "rectangular_pattern",
            entities=["$selection_0"],
            direction_one="$selection_1",
            quantity_one=3,
            distance_one="20 mm",
            direction_two="$selection_2",
            quantity_two=2,
            distance_two="15 mm",
            is_symmetric=True,
        )
    )
    assert payload["quantity_two"] == 2
    assert payload["distance_two"] == "15 mm"
    assert payload["is_symmetric"] is True
    built = _last_feature(fusion)
    assert built.params["quantity_two"] == 2
    assert built.params["is_symmetric"] is True


def test_rectangular_pattern_needs_an_active_design(fusion_empty, call, mcp):
    assert (
        mcp.error_kind(
            call(
                "rectangular_pattern",
                entities=["$selection_0"],
                direction_one="$selection_1",
                quantity_one=3,
                distance_one="20 mm",
            )
        )
        == "no_active_document"
    )


def test_rectangular_pattern_requires_its_required_arguments(fusion, call, mcp):
    fusion.add_edge("Seed", 10.0)
    fusion.add_edge("Axis", 20.0)
    _select(call)

    assert "missing required argument" in mcp.error(
        call(
            "rectangular_pattern",
            entities=[],
            direction_one="$selection_1",
            quantity_one=3,
            distance_one="20 mm",
        )
    )
    assert "missing required argument" in mcp.error(
        call(
            "rectangular_pattern",
            entities=["$selection_0"],
            direction_one="$selection_1",
            quantity_one=3,
        )
    )


def test_rectangular_pattern_rejects_a_count_below_one(fusion, call, mcp):
    fusion.add_edge("Seed", 10.0)
    fusion.add_edge("Axis", 20.0)
    _select(call)

    assert "quantity_one must be at least 1" in mcp.error(
        call(
            "rectangular_pattern",
            entities=["$selection_0"],
            direction_one="$selection_1",
            quantity_one=0,
            distance_one="20 mm",
        )
    )


def test_rectangular_pattern_rejects_non_positive_spacing(fusion, call, mcp):
    fusion.add_edge("Seed", 10.0)
    fusion.add_edge("Axis", 20.0)
    _select(call)

    assert "spacing must be greater than zero" in mcp.error(
        call(
            "rectangular_pattern",
            entities=["$selection_0"],
            direction_one="$selection_1",
            quantity_one=3,
            distance_one="0 mm",
        )
    )


def test_rectangular_pattern_rejects_mixed_entity_kinds(fusion, call, mcp):
    fusion.add_face("Face", area=4.0)
    fusion.add_edge("Edge", 10.0)
    fusion.add_edge("Axis", 20.0)
    _select(call)

    assert "must be the same type" in mcp.error(
        call(
            "rectangular_pattern",
            entities=["$selection_0", "$selection_1"],
            direction_one="$selection_2",
            quantity_one=3,
            distance_one="20 mm",
        )
    )


def test_rectangular_pattern_second_direction_needs_all_three_arguments(fusion, call, mcp):
    fusion.add_edge("Seed", 10.0)
    fusion.add_edge("AxisX", 20.0)
    fusion.add_edge("AxisY", 20.0)
    _select(call)

    assert "quantity_two must be at least 1 when direction_two is set" in mcp.error(
        call(
            "rectangular_pattern",
            entities=["$selection_0"],
            direction_one="$selection_1",
            quantity_one=3,
            distance_one="20 mm",
            direction_two="$selection_2",
        )
    )
    assert "distance_two is required when direction_two is set" in mcp.error(
        call(
            "rectangular_pattern",
            entities=["$selection_0"],
            direction_one="$selection_1",
            quantity_one=3,
            distance_one="20 mm",
            direction_two="$selection_2",
            quantity_two=2,
        )
    )
    assert "spacing must be greater than zero" in mcp.error(
        call(
            "rectangular_pattern",
            entities=["$selection_0"],
            direction_one="$selection_1",
            quantity_one=3,
            distance_one="20 mm",
            direction_two="$selection_2",
            quantity_two=2,
            distance_two="0 mm",
        )
    )


# ── Circular pattern ─────────────────────────────────────────────────────────


def test_circular_pattern_defaults_to_a_full_circle(fusion, call, mcp):
    fusion.add_edge("Seed", 10.0)
    fusion.add_edge("Axis", 20.0)
    _select(call)

    payload = mcp.ok(
        call(
            "circular_pattern",
            entities=["$selection_0"],
            axis="$selection_1",
            quantity=6,
        )
    )
    assert payload["feature_type"] == "CircularPattern"
    assert payload["entity_count"] == 1
    assert payload["quantity"] == 6
    assert payload["total_angle"] == "360 deg"
    assert _last_feature(fusion).params["quantity"] == 6


def test_circular_pattern_honours_a_partial_sweep(fusion, call, mcp):
    fusion.add_edge("Seed", 10.0)
    fusion.add_edge("Axis", 20.0)
    _select(call)

    payload = mcp.ok(
        call(
            "circular_pattern",
            entities=["$selection_0"],
            axis="$selection_1",
            quantity=4,
            total_angle="180 deg",
            is_symmetric=True,
        )
    )
    assert payload["total_angle"] == "180 deg"
    assert payload["is_symmetric"] is True
    assert _last_feature(fusion).params["is_symmetric"] is True


def test_circular_pattern_needs_an_active_design(fusion_empty, call, mcp):
    assert (
        mcp.error_kind(
            call(
                "circular_pattern",
                entities=["$selection_0"],
                axis="$selection_1",
                quantity=6,
            )
        )
        == "no_active_document"
    )


def test_circular_pattern_requires_entities_axis_and_quantity(fusion, call, mcp):
    fusion.add_edge("Seed", 10.0)
    fusion.add_edge("Axis", 20.0)
    _select(call)

    assert "missing required argument" in mcp.error(
        call(
            "circular_pattern",
            entities=[],
            axis="$selection_1",
            quantity=6,
        )
    )
    assert "missing required argument" in mcp.error(
        call(
            "circular_pattern",
            entities=["$selection_0"],
            quantity=6,
        )
    )


def test_circular_pattern_rejects_a_count_below_one(fusion, call, mcp):
    fusion.add_edge("Seed", 10.0)
    fusion.add_edge("Axis", 20.0)
    _select(call)

    assert "quantity must be at least 1" in mcp.error(
        call(
            "circular_pattern",
            entities=["$selection_0"],
            axis="$selection_1",
            quantity=0,
        )
    )


def test_circular_pattern_rejects_a_non_positive_sweep(fusion, call, mcp):
    fusion.add_edge("Seed", 10.0)
    fusion.add_edge("Axis", 20.0)
    _select(call)

    assert "total angle must be greater than zero" in mcp.error(
        call(
            "circular_pattern",
            entities=["$selection_0"],
            axis="$selection_1",
            quantity=6,
            total_angle="0 deg",
        )
    )


# ── Extrude ────────────────────────────────────────────────────────────────────


def _square_profile(call, mcp, plane="xy"):
    """Draw a closed 2 cm square and hand back the handle of its single profile.

    The solid tools address a profile by the handle ``create_sketch`` returned,
    so this is the honest way to give an extrude or revolve test something to
    sweep -- no handle is invented, and the profile is the one the chaining
    detector actually closed.
    """
    payload = mcp.ok(
        call(
            "create_sketch",
            plane=plane,
            curves=[
                {"kind": "line", "start": {"x": 0.0, "y": 0.0, "z": 0.0}, "end": {"x": 2.0, "y": 0.0, "z": 0.0}},
                {"kind": "line", "start": {"x": 2.0, "y": 0.0, "z": 0.0}, "end": {"x": 2.0, "y": 2.0, "z": 0.0}},
                {"kind": "line", "start": {"x": 2.0, "y": 2.0, "z": 0.0}, "end": {"x": 0.0, "y": 2.0, "z": 0.0}},
                {"kind": "line", "start": {"x": 0.0, "y": 2.0, "z": 0.0}, "end": {"x": 0.0, "y": 0.0, "z": 0.0}},
            ],
        )
    )
    assert payload["profile_count"] == 1, "the sketch did not close into a profile"
    return payload["profiles"][0]


def test_extrude_sweeps_a_profile_handle_by_a_distance(fusion, call, mcp):
    profile = _square_profile(call, mcp)

    payload = mcp.ok(call("extrude", profile=profile, distance="10 mm"))

    assert payload["feature_type"] == "Extrude"
    assert payload["feature"] == "Extrude1"
    assert payload["profile"] == profile
    assert payload["operation"] == "new_body"
    assert payload["extent"] == "distance"
    assert payload["distance"] == "10 mm"
    assert payload["direction"] == "positive"
    assert payload["body"].startswith("$body_")

    # The fake recorded the resolved dimension, not the expression string.
    built = _last_feature(fusion)
    assert built.params["distance_cm"] == 1.0
    assert built.params["extent"] == "one_side"


def test_extrude_round_trips_every_combination_operation(fusion, call, mcp):
    profile = _square_profile(call, mcp)
    enumerators = {
        "new_body": values.FeatureOperations.NewBodyFeatureOperation,
        "join": values.FeatureOperations.JoinFeatureOperation,
        "cut": values.FeatureOperations.CutFeatureOperation,
        "intersect": values.FeatureOperations.IntersectFeatureOperation,
    }

    for operation, enumerator in enumerators.items():
        payload = mcp.ok(call("extrude", profile=profile, operation=operation, distance="5 mm"))
        assert payload["operation"] == operation
        # The fake records the FeatureOperations enumerator the name mapped to.
        assert _last_feature(fusion).params["operation"] == enumerator


def test_extrude_runs_the_other_way_with_a_negative_direction(fusion, call, mcp):
    profile = _square_profile(call, mcp)

    payload = mcp.ok(call("extrude", profile=profile, distance="10 mm", direction="negative"))

    assert payload["direction"] == "negative"
    assert payload["distance"] == "10 mm"


def test_extrude_through_all_reports_no_distance(fusion, call, mcp):
    profile = _square_profile(call, mcp)

    payload = mcp.ok(call("extrude", profile=profile, extent="through_all"))

    assert payload["extent"] == "through_all"
    assert payload["distance"] is None
    # A through-all extent is bounded by the bodies it meets; the fake builds the
    # feature without fabricating a span, so no body handle is published.
    assert payload["body"] is None
    assert _last_feature(fusion).params["distance_cm"] is None


def test_extrude_symmetric_sweeps_both_ways_and_reports_no_direction(fusion, call, mcp):
    profile = _square_profile(call, mcp)

    payload = mcp.ok(call("extrude", profile=profile, extent="symmetric", distance="5 mm"))

    assert payload["extent"] == "symmetric"
    assert payload["distance"] == "5 mm"
    assert payload["direction"] is None
    assert _last_feature(fusion).params["extent"] == "symmetric"


def test_extrude_distance_is_required_for_distance_and_symmetric_extents(fusion, call, mcp):
    profile = _square_profile(call, mcp)

    assert "distance is required" in mcp.error(call("extrude", profile=profile))
    assert "distance is required" in mcp.error(call("extrude", profile=profile, extent="symmetric"))


def test_extrude_rejects_an_unknown_extent(fusion, call, mcp):
    profile = _square_profile(call, mcp)
    response = call("extrude", profile=profile, extent="sideways", distance="1 mm")

    assert mcp.error_kind(response) == "invalid_value"
    assert "extent must be 'distance', 'through_all', or 'symmetric'" in mcp.error(response)


def test_extrude_rejects_an_unknown_operation(fusion, call, mcp):
    profile = _square_profile(call, mcp)
    response = call("extrude", profile=profile, operation="weld", distance="1 mm")

    assert mcp.error_kind(response) == "invalid_value"
    assert "operation must be one of 'new_body', 'join', 'cut', or 'intersect'" in mcp.error(response)


def test_extrude_rejects_an_unknown_direction(fusion, call, mcp):
    profile = _square_profile(call, mcp)
    response = call("extrude", profile=profile, distance="1 mm", direction="up")

    assert mcp.error_kind(response) == "invalid_value"
    assert "direction must be 'positive' or 'negative'" in mcp.error(response)


def test_extrude_rejects_a_profile_handle_that_is_not_in_the_store(fusion, call, mcp):
    response = call("extrude", profile="$profile_no_such_0", distance="1 mm")

    assert mcp.error_kind(response) == "invalid_value"
    assert "not found" in mcp.error(response)


def test_extrude_needs_an_active_design(fusion_empty, call, mcp):
    assert mcp.error_kind(call("extrude", profile="$profile_0", distance="1 mm")) == "no_active_document"


# ── Revolve ────────────────────────────────────────────────────────────────────


def test_revolve_sweeps_a_profile_a_full_turn_about_a_construction_axis(fusion, call, mcp):
    profile = _square_profile(call, mcp)

    payload = mcp.ok(call("revolve", profile=profile, axis="y"))

    assert payload["feature_type"] == "Revolve"
    assert payload["feature"] == "Revolve1"
    assert payload["profile"] == profile
    assert payload["axis"] == "y"
    assert payload["operation"] == "new_body"
    assert payload["angle"] == "360 deg"


def test_revolve_honours_a_partial_angle(fusion, call, mcp):
    profile = _square_profile(call, mcp)

    payload = mcp.ok(call("revolve", profile=profile, axis="y", angle="270 deg"))

    assert payload["angle"] == "270 deg"
    built = _last_feature(fusion)
    assert built.params["angle_deg"] == 270.0
    assert built.params["is_symmetric"] is False


def test_revolve_accepts_a_stored_axis_handle(fusion, call, mcp):
    profile = _square_profile(call, mcp)
    fusion.add_edge("AxisEdge", 20.0)
    _select(call)

    payload = mcp.ok(call("revolve", profile=profile, axis="$selection_0", angle="180 deg"))

    assert payload["feature_type"] == "Revolve"
    assert payload["axis"] == "$selection_0"


def test_revolve_rejects_an_axis_that_is_neither_a_handle_nor_an_axis_name(fusion, call, mcp):
    profile = _square_profile(call, mcp)
    response = call("revolve", profile=profile, axis="diagonal")

    assert mcp.error_kind(response) == "invalid_value"
    assert "entity must be a stored selection handle" in mcp.error(response)


def test_revolve_rejects_an_axis_handle_that_is_not_in_the_store(fusion, call, mcp):
    profile = _square_profile(call, mcp)
    response = call("revolve", profile=profile, axis="$selection_99")

    assert mcp.error_kind(response) == "invalid_value"
    assert "not found" in mcp.error(response)


def test_revolve_needs_an_active_design(fusion_empty, call, mcp):
    assert mcp.error_kind(call("revolve", profile="$profile_0", axis="y")) == "no_active_document"


# ── Component ──────────────────────────────────────────────────────────────────


def test_create_component_names_a_new_component_in_the_assembly(fusion, call, mcp):
    payload = mcp.ok(call("create_component", name="Bracket"))

    assert payload["name"] == "Bracket"
    assert payload["component"].startswith("$component_")
    assert payload["occurrence"].startswith("$occurrence_")

    # The component is reached through the occurrence the API created it from.
    assert fusion.root.occurrences.count == 1
    assert fusion.root.occurrences.item(0).component.name == "Bracket"


def test_create_component_rejects_an_unnamed_component(fusion, call, mcp):
    assert "missing required argument" in mcp.error(call("create_component", name=""))
    response = call("create_component", name="   ")

    assert mcp.error_kind(response) == "invalid_value"
    assert "name must be a non-empty string" in mcp.error(response)


def test_create_component_needs_an_active_design(fusion_empty, call, mcp):
    assert mcp.error_kind(call("create_component", name="Bracket")) == "no_active_document"


def _must_not_be_called(*args, **kwargs):
    raise AssertionError("create_component must not reach the addNewComponent API for a part document")


def test_create_component_refuses_a_part_shaped_document_before_the_api_is_called(fusion, call, mcp, monkeypatch):
    # Zero occurrences with real geometry in the root: this looks like a part
    # document, where addNewComponent fails opaquely in real Fusion.
    fusion.new_document("Bracket")
    fusion.add_body("Base", shape="box", length=2.0, width=2.0, height=2.0, select=False)
    assert fusion.root.occurrences.count == 0
    assert fusion.root.bodies.count == 1

    monkeypatch.setattr(fusion.root.occurrences, "addNewComponent", _must_not_be_called)

    response = call("create_component", name="Bracket")

    assert mcp.error_kind(response) == "unsupported_operation"
    message = mcp.error(response)
    assert "part" in message.lower()
    assert "assembly" in message.lower()
    hint = mcp.error_hint(response)
    assert "root component" in hint.lower()
    assert "assembly" in hint.lower()
    # No silent fallback to the root component: nothing was created.
    assert fusion.root.occurrences.count == 0


def test_create_component_proceeds_when_the_document_is_an_assembly(fusion, call, mcp):
    # One existing occurrence makes this an assembly, so the guard must not fire.
    fusion.root.occurrences.add(FakeComponent("Existing"), "Existing")
    assert fusion.root.occurrences.count == 1

    payload = mcp.ok(call("create_component", name="Bracket"))

    assert payload["name"] == "Bracket"
    assert payload["component"].startswith("$component_")
    assert fusion.root.occurrences.count == 2
    assert fusion.root.occurrences.item(1).component.name == "Bracket"


# ── Body primitives ────────────────────────────────────────────────────────────


def test_create_body_adds_a_named_box_to_the_root_component(fusion, call, mcp):
    payload = mcp.ok(
        call("create_body", shape="box", dimensions={"length": 2.0, "width": 3.0, "height": 4.0}, name="Housing")
    )

    assert payload["shape"] == "box"
    assert payload["name"] == "Housing"
    assert payload["is_solid"] is True
    assert payload["body"].startswith("$body_")

    body = fusion.root.bodies.item(0)
    assert body.name == "Housing"
    assert body.isSolid is True
    # A parametric design wraps the primitive in a base feature's edit cycle.
    assert _last_feature(fusion).name.startswith("BaseFeature")


def test_create_body_builds_a_cylinder(fusion, call, mcp):
    payload = mcp.ok(call("create_body", shape="cylinder", dimensions={"radius": 1.0, "height": 5.0}))

    assert payload["shape"] == "cylinder"
    assert payload["is_solid"] is True
    assert fusion.root.bodies.count == 1


def test_create_body_builds_a_sphere(fusion, call, mcp):
    payload = mcp.ok(call("create_body", shape="sphere", dimensions={"radius": 2.0}))

    assert payload["shape"] == "sphere"
    assert payload["is_solid"] is True
    assert fusion.root.bodies.count == 1


def test_create_body_adds_directly_in_a_direct_design(fusion, call, mcp):
    # A direct design has no timeline edit cycle to wrap the primitive in.
    fusion.design.designType = values.DesignTypes.DirectDesignType

    payload = mcp.ok(call("create_body", shape="box", dimensions={"length": 1.0, "width": 1.0, "height": 1.0}))

    assert payload["shape"] == "box"
    assert payload["is_solid"] is True
    assert fusion.root.bodies.count == 1
    assert fusion.root.features.count == 0


def test_create_body_requires_shape_and_dimensions(fusion, call, mcp):
    assert "missing required argument" in mcp.error(call("create_body", dimensions={"radius": 1.0}))
    assert "missing required argument" in mcp.error(call("create_body", shape="sphere"))


def test_create_body_rejects_an_unknown_shape(fusion, call, mcp):
    response = call("create_body", shape="pyramid", dimensions={"length": 1.0, "width": 1.0, "height": 1.0})

    assert mcp.error_kind(response) == "invalid_value"
    assert "shape must be 'box', 'cylinder', or 'sphere'" in mcp.error(response)


def test_create_body_rejects_non_positive_dimensions(fusion, call, mcp):
    zero_height = call("create_body", shape="box", dimensions={"length": 1.0, "width": 1.0, "height": 0})
    assert mcp.error_kind(zero_height) == "invalid_value"
    assert "height must be greater than zero" in mcp.error(zero_height)

    negative_radius = call("create_body", shape="sphere", dimensions={"radius": -1.0})
    assert "radius must be greater than zero" in mcp.error(negative_radius)


def test_create_body_requires_every_dimension_the_shape_needs(fusion, call, mcp):
    # An empty dimensions object is the caller forgetting, not a bad value.
    assert mcp.error_kind(call("create_body", shape="sphere", dimensions={})) == "missing_argument"

    # A sphere given the wrong dimension has no radius to build from.
    response = call("create_body", shape="sphere", dimensions={"height": 1.0})
    assert mcp.error_kind(response) == "invalid_value"
    assert "radius must be a number" in mcp.error(response)


def test_create_body_needs_an_active_design(fusion_empty, call, mcp):
    response = call("create_body", shape="box", dimensions={"length": 1.0, "width": 1.0, "height": 1.0})
    assert mcp.error_kind(response) == "no_active_document"


# ── Appearance ─────────────────────────────────────────────────────────────────


def test_apply_appearance_assigns_a_library_appearance_to_a_body(fusion, call, mcp):
    body = mcp.ok(call("create_body", shape="box", dimensions={"length": 2.0, "width": 2.0, "height": 2.0}))["body"]

    payload = mcp.ok(call("apply_appearance", body=body, appearance="Steel"))

    assert payload["body"] == body
    assert payload["appearance"] == "Steel"
    assert payload["library"] == "Fusion 360 Material Library"
    assert payload["appearance_name"] == "Steel"

    # The appearance was copied into the design and assigned to the body itself.
    assert fusion.design.appearances.itemByName("Steel") is not None
    assert fusion.root.bodies.item(0).appearance.name == "Steel"


def test_apply_appearance_reads_an_explicit_library(fusion, call, mcp):
    fusion.app.materialLibraries = FakeMaterialLibraries(
        [
            FakeMaterialLibrary("Fusion 360 Material Library", ("Steel",)),
            FakeMaterialLibrary("Finishes", ("Powder Coat",)),
        ]
    )
    body = mcp.ok(call("create_body", shape="sphere", dimensions={"radius": 1.0}))["body"]

    payload = mcp.ok(call("apply_appearance", body=body, appearance="Powder Coat", library="Finishes"))

    assert payload["library"] == "Finishes"
    assert payload["appearance"] == "Powder Coat"
    assert payload["appearance_name"] == "Powder Coat"


def test_apply_appearance_reports_an_unknown_library(fusion, call, mcp):
    body = mcp.ok(call("create_body", shape="box", dimensions={"length": 1.0, "width": 1.0, "height": 1.0}))["body"]
    response = call("apply_appearance", body=body, appearance="Steel", library="Nope")

    assert mcp.error_kind(response) == "not_found"
    assert "No material library named" in mcp.error(response)


def test_apply_appearance_reports_an_unknown_appearance(fusion, call, mcp):
    body = mcp.ok(call("create_body", shape="box", dimensions={"length": 1.0, "width": 1.0, "height": 1.0}))["body"]
    response = call("apply_appearance", body=body, appearance="Unobtanium")

    assert mcp.error_kind(response) == "not_found"
    assert "No appearance named" in mcp.error(response)


def test_apply_appearance_rejects_an_empty_appearance_name(fusion, call, mcp):
    body = mcp.ok(call("create_body", shape="box", dimensions={"length": 1.0, "width": 1.0, "height": 1.0}))["body"]

    assert "missing required argument" in mcp.error(call("apply_appearance", body=body, appearance=""))
    response = call("apply_appearance", body=body, appearance="   ")

    assert mcp.error_kind(response) == "invalid_value"
    assert "appearance must be a non-empty appearance name" in mcp.error(response)


def test_apply_appearance_needs_an_active_design(fusion_empty, call, mcp):
    assert mcp.error_kind(call("apply_appearance", body="$body_0", appearance="Steel")) == "no_active_document"
