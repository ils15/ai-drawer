"""create_sketch tool tests against the behavioral fake.

The sketch tool is the modelling spine: it draws curves on a base construction
plane and publishes one handle per closed profile it derived from them, because
there is no other way for a caller to know which closed region the API decided a
set of curves formed.  So the interesting assertions here are not "a call
returned a payload" but two things the fake computes for real:

* endpoint chaining decides whether a profile exists -- four lines that close
  into a square publish one profile, two unconnected lines publish none, and a
  circle is its own closed loop;
* the arc sweep is carried in friendly degrees and converted to radians on the
  way in, which the fake verifies geometrically: a 90-degree sweep about a
  centre must land the arc's end point exactly one quarter turn away.
"""

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)
import pytest


def _square_curves(size=2.0):
    """Four chained lines closing into a square of the given side, in cm."""
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


# ── Happy paths ───────────────────────────────────────────────────────────────


def test_create_sketch_chains_four_lines_into_one_profile(fusion, call, mcp):
    payload = mcp.ok(call("create_sketch", plane="xy", curves=_square_curves()))

    assert payload["plane"] == "xy"
    assert payload["curve_count"] == 4
    assert payload["name"] == "Sketch1"
    assert payload["sketch"].startswith("$sketch_")
    assert payload["profile_count"] == 1
    assert payload["profiles"][0].startswith("$profile_")

    # The sketch is a real object on the root component, not just a handle.
    assert fusion.root.sketches.count == 1
    assert fusion.root.sketches.item(0).sketchCurves.count == 4


def test_create_sketch_publishes_one_profile_handle_per_closed_region(fusion, call, mcp):
    # Two disjoint squares on one sketch: two closed regions, two handles.
    curves = _square_curves()
    curves.extend(
        [
            {"kind": "line", "start": {"x": 5.0, "y": 0.0, "z": 0.0}, "end": {"x": 7.0, "y": 0.0, "z": 0.0}},
            {"kind": "line", "start": {"x": 7.0, "y": 0.0, "z": 0.0}, "end": {"x": 7.0, "y": 2.0, "z": 0.0}},
            {"kind": "line", "start": {"x": 7.0, "y": 2.0, "z": 0.0}, "end": {"x": 5.0, "y": 2.0, "z": 0.0}},
            {"kind": "line", "start": {"x": 5.0, "y": 2.0, "z": 0.0}, "end": {"x": 5.0, "y": 0.0, "z": 0.0}},
        ]
    )
    payload = mcp.ok(call("create_sketch", plane="xy", curves=curves))

    assert payload["curve_count"] == 8
    assert payload["profile_count"] == 2
    handles = payload["profiles"]
    assert handles[0].startswith("$profile_")
    assert handles[1].startswith("$profile_")
    assert handles[0] != handles[1]


def test_create_sketch_accepts_the_xz_and_yz_planes(fusion, call, mcp):
    for plane in ("xz", "yz"):
        payload = mcp.ok(
            call(
                "create_sketch",
                plane=plane,
                curves=[{"kind": "circle", "center": {"x": 0, "y": 0, "z": 0}, "radius": 1.0}],
            )
        )
        assert payload["plane"] == plane
        assert payload["profile_count"] == 1


def test_create_sketch_circle_is_its_own_closed_profile(fusion, call, mcp):
    payload = mcp.ok(
        call(
            "create_sketch",
            plane="xy",
            curves=[{"kind": "circle", "center": {"x": 0.0, "y": 0.0, "z": 0.0}, "radius": 1.5}],
        )
    )

    assert payload["curve_count"] == 1
    assert payload["profile_count"] == 1
    assert payload["profiles"][0].startswith("$profile_")


def test_create_sketch_converts_an_arc_sweep_from_degrees_to_radians(fusion, call, mcp):
    # A quarter turn about (1, 1) starting at (2, 1): 90 degrees counter-clockwise
    # must end at (1, 2).  Had the sweep been handed to the API in degrees, the
    # endpoint would be somewhere entirely else and the chain below would not
    # close, so profile_count is the geometric proof of the conversion.
    payload = mcp.ok(
        call(
            "create_sketch",
            plane="xy",
            curves=[
                {
                    "kind": "arc",
                    "center": {"x": 1.0, "y": 1.0, "z": 0.0},
                    "start": {"x": 2.0, "y": 1.0, "z": 0.0},
                    "sweep": 90,
                },
                {"kind": "line", "start": {"x": 1.0, "y": 2.0, "z": 0.0}, "end": {"x": 2.0, "y": 2.0, "z": 0.0}},
                {"kind": "line", "start": {"x": 2.0, "y": 2.0, "z": 0.0}, "end": {"x": 2.0, "y": 1.0, "z": 0.0}},
            ],
        )
    )

    assert payload["curve_count"] == 3
    assert payload["profile_count"] == 1

    arc = fusion.root.sketches.item(0).sketchCurves.item(0)
    assert arc.end.x == pytest.approx(1.0)
    assert arc.end.y == pytest.approx(2.0)


def test_create_sketch_an_open_chain_publishes_no_profile(fusion, call, mcp):
    payload = mcp.ok(
        call(
            "create_sketch",
            plane="xy",
            curves=[
                {"kind": "line", "start": {"x": 0.0, "y": 0.0, "z": 0.0}, "end": {"x": 2.0, "y": 0.0, "z": 0.0}},
                {"kind": "line", "start": {"x": 5.0, "y": 5.0, "z": 0.0}, "end": {"x": 7.0, "y": 5.0, "z": 0.0}},
            ],
        )
    )

    assert payload["curve_count"] == 2
    assert payload["profile_count"] == 0
    assert payload["profiles"] == []


def test_create_sketch_profiles_thread_into_extrude_and_revolve(fusion, call, mcp):
    # The whole point of publishing a handle: the caller hands the *returned*
    # profile to the solid tools without a reverse lookup the bridge does not keep.
    sketch = mcp.ok(call("create_sketch", plane="xy", curves=_square_curves()))
    profile = sketch["profiles"][0]

    extruded = mcp.ok(call("extrude", profile=profile, distance="10 mm"))
    assert extruded["feature_type"] == "Extrude"
    assert extruded["profile"] == profile
    assert extruded["body"].startswith("$body_")

    revolved = mcp.ok(call("revolve", profile=profile, axis="y", angle="180 deg"))
    assert revolved["feature_type"] == "Revolve"
    assert revolved["profile"] == profile


# ── Errors ─────────────────────────────────────────────────────────────────────


def test_create_sketch_needs_an_active_design(fusion_empty, call, mcp):
    assert mcp.error_kind(call("create_sketch", plane="xy", curves=_square_curves())) == "no_active_document"


def test_create_sketch_requires_a_plane_and_curves(fusion, call, mcp):
    assert "missing required argument" in mcp.error(call("create_sketch", curves=_square_curves()))
    assert "missing required argument" in mcp.error(call("create_sketch", plane="xy"))


def test_create_sketch_rejects_an_unknown_plane(fusion, call, mcp):
    assert mcp.error_kind(call("create_sketch", plane="abc", curves=_square_curves())) == "invalid_value"
    assert "plane must be 'xy', 'xz', or 'yz'" in mcp.error(call("create_sketch", plane="XYZ", curves=_square_curves()))


def test_create_sketch_requires_at_least_one_curve(fusion, call, mcp):
    # An empty array is the caller forgetting, so it is reported as a missing
    # argument rather than a bad value -- the same rule as fillet's empty edges.
    assert mcp.error_kind(call("create_sketch", plane="xy", curves=[])) == "missing_argument"
    # A non-empty non-array is a value of the wrong shape.
    assert "curves must be an array" in mcp.error(call("create_sketch", plane="xy", curves="line"))


def test_create_sketch_rejects_an_unknown_curve_kind(fusion, call, mcp):
    curves = [{"kind": "spline", "start": {"x": 0, "y": 0, "z": 0}, "end": {"x": 1, "y": 1, "z": 0}}]
    assert mcp.error_kind(call("create_sketch", plane="xy", curves=curves)) == "invalid_value"
    assert "curve kind must be 'line', 'circle', or 'arc'" in mcp.error(
        call("create_sketch", plane="xy", curves=curves)
    )


def test_create_sketch_rejects_a_non_positive_circle_radius(fusion, call, mcp):
    zero = [{"kind": "circle", "center": {"x": 0, "y": 0, "z": 0}, "radius": 0}]
    assert "radius must be greater than zero" in mcp.error(call("create_sketch", plane="xy", curves=zero))

    negative = [{"kind": "circle", "center": {"x": 0, "y": 0, "z": 0}, "radius": -1.0}]
    assert "radius must be greater than zero" in mcp.error(call("create_sketch", plane="xy", curves=negative))


def test_create_sketch_rejects_a_non_object_curve(fusion, call, mcp):
    assert "each curve must be an object" in mcp.error(call("create_sketch", plane="xy", curves=["line"]))


def test_create_sketch_rejects_a_malformed_point(fusion, call, mcp):
    # A point missing its z coordinate is not a point in 3D space.
    curves = [{"kind": "line", "start": {"x": 0.0, "y": 0.0}, "end": {"x": 1.0, "y": 1.0, "z": 0.0}}]
    assert mcp.error_kind(call("create_sketch", plane="xy", curves=curves)) == "invalid_value"
    assert "start must be an object with numeric x, y, and z" in mcp.error(
        call("create_sketch", plane="xy", curves=curves)
    )
