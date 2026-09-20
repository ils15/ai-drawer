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
