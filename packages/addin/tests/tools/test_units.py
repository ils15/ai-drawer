"""Units convention: bare numbers are rescaled once on the way in, Fusion
expressions pass through untouched, and the tool-level ``units`` field is the
single switch for every length on the tool.

These tests pin three things that are easy to regress silently:

* the arithmetic of ``to_cm`` (92 mm is 9.2 cm, not 0.92);
* a number is rescaled exactly once and an expression never is -- converting
  an expression would double-apply its own unit;
* the ``units`` field reaches every length on the tool, so a caller drawing
  in millimetres gets millimetres everywhere, not just the first argument.

The tool-level field is read once per call by ``read_units`` and threaded
through the same helpers, so one tool per shape is enough to prove the wiring.
"""

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)
import pytest

from fusion_bridge import tool_surface

# ── Arithmetic ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("units, factor", [("mm", 0.1), ("cm", 1.0), ("in", 2.54), ("m", 100.0)])
def test_to_cm_rescales_a_bare_number_once(units, factor):
    # 92 mm is 9.2 cm.  The docstring once said 0.92, which is the kind of
    # silent arithmetic bug that makes a model print at a tenth of its size.
    from fusion_bridge import value_builders


    assert value_builders.to_cm(92, units) == pytest.approx(92 * factor)


@pytest.mark.parametrize("units", sorted(tool_surface.LENGTH_UNITS))
def test_to_cm_accepts_every_advertised_unit(units):
    from fusion_bridge import value_builders


    assert value_builders.to_cm(5, units) == pytest.approx(5 * value_builders.to_cm(1, units))


def test_to_cm_defaults_to_centimetres():
    from fusion_bridge import value_builders


    assert value_builders.to_cm(5) == pytest.approx(5.0)


def test_to_cm_rejects_an_unknown_unit():
    from fusion_bridge import value_builders

    with pytest.raises(ValueError, match="units must be one of"):
        value_builders.to_cm(5, "feet")


def test_the_unit_lists_agree_between_the_contract_and_the_builders():
    # The schema's enum and the builder's lookup table are two copies of one
    # list; a value accepted by the schema but unknown to the builder would slip
    # past validation and fail deep inside a tool.
    from fusion_bridge import value_builders

    assert list(tool_surface.LENGTH_UNITS) == list(value_builders.LENGTH_UNITS)


# ── ValueInput construction ──────────────────────────────────────────────────


@pytest.mark.parametrize("units, factor", [("mm", 0.1), ("cm", 1.0), ("in", 2.54), ("m", 100.0)])
def test_a_bare_number_becomes_a_real_in_centimetres(fusion, units, factor):
    from fusion_bridge import operations

    value = operations.features._to_value_input(10, units)
    assert value.real == pytest.approx(10 * factor)
    assert value.expression is None


def test_an_expression_passes_through_untouched_and_ignores_units(fusion):
    from fusion_bridge import operations

    # "92 mm" already names its unit; rescaling it would double-apply.  The
    # expression engine resolves units natively, whatever the tool's units are.
    for units in ("mm", "cm", "in", "m"):
        value = operations.features._to_value_input("92 mm", units)
        assert value.expression == "92 mm"
        assert value.real is None


def test_a_parameter_expression_passes_through(fusion):
    from fusion_bridge import operations

    value = operations.features._to_value_input("width/2", "mm")
    assert value.expression == "width/2"


def test_a_boolean_is_still_rejected(fusion):
    from fusion_bridge import operations

    with pytest.raises(ValueError, match="boolean is not a valid dimension"):
        operations.features._to_value_input(True, "mm")


def test_a_numeric_string_is_an_expression_not_a_number(fusion):
    # "10" is handed to the engine as text, so it is not rescaled even in mm.
    from fusion_bridge import operations

    value = operations.features._to_value_input("10", "mm")
    assert value.expression == "10"
    assert value.real is None


# ── The tool-level units field ───────────────────────────────────────────────


def _select(call):
    return call("get_active_selection")


def test_every_unit_aware_tool_advertises_the_units_field():
    # A tool that rescales numbers must accept the switch that selects the scale.
    from fusion_bridge import value_builders


    for name in ("fillet", "chamfer", "hole", "rectangular_pattern", "create_sketch", "extrude", "create_body"):
        schema = next(tool for tool in tool_surface.TOOL_DEFINITIONS if tool["name"] == name)["inputSchema"]
        assert "units" in schema["properties"], name
        # units is optional and never required: the default is centimetres.
        assert "units" not in schema.get("required", [])
        assert schema["properties"]["units"]["enum"] == list(value_builders.LENGTH_UNITS)


def test_fillet_rescales_a_bare_number_from_millimetres(fusion, call, mcp):
    fusion.add_edge("Edge", 100.0)
    _select(call)

    payload = mcp.ok(call("fillet", edges=["$selection_0"], radius=5, units="mm"))
    assert payload["radius"] == 5
    # The fake records the resolved internal value, in centimetres.
    feature = list(fusion.design.rootComponent.features)[-1]
    assert feature.params["radius_cm"] == pytest.approx(0.5)


def test_fillet_defaults_to_centimetres_without_the_field(fusion, call, mcp):
    fusion.add_edge("Edge", 100.0)
    _select(call)

    payload = mcp.ok(call("fillet", edges=["$selection_0"], radius=0.5))
    feature = list(fusion.design.rootComponent.features)[-1]
    assert payload["radius"] == 0.5
    assert feature.params["radius_cm"] == pytest.approx(0.5)


def test_an_expression_is_not_rescaled_even_in_millimetres(fusion, call, mcp):
    # "5 mm" is resolved by the expression engine, so units="mm" must not
    # touch it -- this is the regression that would shrink a model tenfold.
    fusion.add_edge("Edge", 100.0)
    _select(call)

    payload = mcp.ok(call("fillet", edges=["$selection_0"], radius="5 mm", units="mm"))
    feature = list(fusion.design.rootComponent.features)[-1]
    assert payload["radius"] == "5 mm"
    assert feature.params["radius_cm"] == pytest.approx(0.5)


def test_an_unknown_unit_is_reported_as_an_invalid_value(fusion, call, mcp):
    fusion.add_edge("Edge", 100.0)
    _select(call)

    assert mcp.error_kind(call("fillet", edges=["$selection_0"], radius=5, units="feet")) == "invalid_value"
    assert "units must be one of" in mcp.error(call("fillet", edges=["$selection_0"], radius=5, units="feet"))


def test_create_body_rescales_every_dimension_from_millimetres(fusion, call, mcp):
    # 20 x 20 x 30 mm is 2 x 2 x 3 cm; the bounding box is the geometric proof.
    mcp.ok(
        call(
            "create_body",
            shape="box",
            dimensions={"length": 20, "width": 20, "height": 30},
            units="mm",
        )
    )

    box = fusion.root.bodies.item(0).boundingBox
    assert box.maxPoint.x == pytest.approx(2.0)
    assert box.maxPoint.y == pytest.approx(2.0)
    assert box.maxPoint.z == pytest.approx(3.0)


def test_chamfer_takes_a_bare_number_in_millimetres(fusion, call, mcp):
    # The widened schema takes a number or an expression; the number path is
    # rescaled from the tool's units, the expression carries its own.  Fillet
    # covers the expression path; this covers the number path on a second tool.
    fusion.add_edge("Edge", 100.0)
    _select(call)

    payload = mcp.ok(call("chamfer", edges=["$selection_0"], distance=2, units="mm"))
    feature = list(fusion.design.rootComponent.features)[-1]
    assert payload["distance"] == 2
    assert feature.params["distance_cm"] == pytest.approx(0.2)


def _square_curves_cm(size=2.0):
    near = {"x": 0.0, "y": 0.0, "z": 0.0}
    far_x = {"x": size, "y": 0.0, "z": 0.0}
    far_xy = {"x": size, "y": size, "z": 0.0}
    far_y = {"x": 0.0, "y": size, "z": 0.0}
    return [
        {"kind": "line", "start": near, "end": far_x},
        {"kind": "line", "start": far_x, "end": far_xy},
        {"kind": "line", "start": far_xy, "end": far_y},
        {"kind": "line", "start": far_y, "end": near},
    ]


def test_create_sketch_rescales_curve_points_from_millimetres(fusion, call, mcp):
    # A 20 mm square is 2 cm on a side; the closed profile is the proof that
    # the endpoints chained where the converted points said they would.
    near = {"x": 0, "y": 0, "z": 0}
    far_x = {"x": 20, "y": 0, "z": 0}
    far_xy = {"x": 20, "y": 20, "z": 0}
    far_y = {"x": 0, "y": 20, "z": 0}
    curves = [
        {"kind": "line", "start": near, "end": far_x},
        {"kind": "line", "start": far_x, "end": far_xy},
        {"kind": "line", "start": far_xy, "end": far_y},
        {"kind": "line", "start": far_y, "end": near},
    ]

    payload = mcp.ok(call("create_sketch", plane="xy", curves=curves, units="mm"))
    assert payload["profile_count"] == 1

    line = fusion.root.sketches.item(0).sketchCurves.item(0)
    assert line.end.x == pytest.approx(2.0)


def test_create_sketch_rescales_a_circle_radius(fusion, call, mcp):
    mcp.ok(
        call(
            "create_sketch",
            plane="xy",
            curves=[{"kind": "circle", "center": {"x": 0, "y": 0, "z": 0}, "radius": 50}],
            units="mm",
        )
    )

    circle = fusion.root.sketches.item(0).sketchCurves.item(0)
    # 50 mm radius is 5 cm.
    assert circle.radius == pytest.approx(5.0)


def test_extrude_rescales_a_bare_distance_from_inches(fusion, call, mcp):
    sketch = mcp.ok(call("create_sketch", plane="xy", curves=_square_curves_cm()))
    profile = sketch["profiles"][0]

    # 1 inch is 2.54 cm; the fake records the resolved distance in centimetres.
    payload = mcp.ok(call("extrude", profile=profile, distance=1, units="in"))
    built = list(fusion.design.rootComponent.features)[-1]
    assert built.params["distance_cm"] == pytest.approx(2.54)
    assert payload["distance"] == 1


def test_hole_rescales_position_diameter_and_depth(fusion, call, mcp):
    fusion.add_face("TopFace", area=400.0)
    _select(call)

    payload = mcp.ok(
        call(
            "hole",
            face="$selection_0",
            position={"x": 10, "y": 10, "z": 0},
            diameter=8,
            extent="distance",
            depth=10,
            units="mm",
        )
    )
    assert payload["diameter"] == 8
    feature = list(fusion.design.rootComponent.features)[-1]
    assert feature.params["diameter_cm"] == pytest.approx(0.8)
    assert feature.params["depth_cm"] == pytest.approx(1.0)
