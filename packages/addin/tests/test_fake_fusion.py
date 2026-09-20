"""Correctness tests for the behavioral fake itself.

These do not exercise any shipped tool.  They prove the fake computes what it
claims to compute, so that a tool test that passes against it is meaningful:

* profile closure is decided by real endpoint chaining, not by a flag;
* ``computeAll`` actually re-evaluates the timeline and moves indices;
* the expression engine folds units into the internal centimetre representation.

If any of these fail, the fake is agreeing with a wrong assumption and every
tool test built on it is worthless -- that is the exact failure mode this file
exists to catch.
"""

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)
import pytest
from fake_fusion import make_fusion, values
from fake_fusion.design import evaluate_expression
from fake_fusion.geometry import Point3D


def _value_input(expression):
    """Build a ValueInput the way ``adsk.core.ValueInput`` does, via the pinned static."""
    return values.ValueInput.createByString(expression)


def _sketch(fusion):
    """A fresh sketch on the root component."""
    return fusion.design.rootComponent.sketches.add()


def _extrude(fusion, profile, distance, name):
    """Add an extrude feature over a closed profile."""
    return fusion.design.rootComponent.features.add_extrude(profile, distance, name)


def _rect(fusion, width=2.0, height=2.0, origin=(0.0, 0.0)):
    """Draw a closed rectangle and return its single closed profile."""
    sketch = _sketch(fusion)
    x0, y0 = origin
    x1, y1 = x0 + width, y0 + height
    sketch.add_line(x0, y0, x1, y0)
    sketch.add_line(x1, y0, x1, y1)
    sketch.add_line(x1, y1, x0, y1)
    sketch.add_line(x0, y1, x0, y0)
    return sketch.profiles.item(0)


def test_closed_rectangle_yields_one_profile(fusion):
    profile = _rect(fusion, 4.0, 3.0)
    sketch = fusion.design.rootComponent.sketches.item(0)

    assert sketch.profiles.count == 1
    assert len(profile.curves) == 4
    # Shoelace area of a 4 cm x 3 cm rectangle, in internal cm units.
    assert profile.area == 12.0


def test_closed_circle_is_its_own_profile(fusion):
    sketch = _sketch(fusion)
    sketch.add_circle(0, 0, 2.0)

    assert sketch.profiles.count == 1
    profile = sketch.profiles.item(0)
    # A circle's start and end coincide, so it chains to itself.
    assert profile.curves[0].geometry == "circle"


def test_closed_polyline_chain_of_three_sides(fusion):
    sketch = _sketch(fusion)
    # A triangle built as an unordered chain: the closure detector must
    # assemble it regardless of the order the curves were added.
    sketch.add_line(0, 0, 2, 0)
    sketch.add_line(1, 2, 0, 0)
    sketch.add_line(2, 0, 1, 2)

    assert sketch.profiles.count == 1
    assert len(sketch.profiles.item(0).curves) == 3


def test_two_separate_closed_loops_are_two_profiles(fusion):
    sketch = _sketch(fusion)
    for corner in ((0, 0), (10, 10)):
        sketch.add_line(corner[0], corner[1], corner[0] + 2, corner[1])
        sketch.add_line(corner[0] + 2, corner[1], corner[0] + 2, corner[1] + 2)
        sketch.add_line(corner[0] + 2, corner[1] + 2, corner[0], corner[1] + 2)
        sketch.add_line(corner[0], corner[1] + 2, corner[0], corner[1])

    assert sketch.profiles.count == 2


def test_open_line_chain_yields_no_profile(fusion):
    sketch = _sketch(fusion)
    # Three lines forming a "C" that never closes.
    sketch.add_line(0, 0, 4, 0)
    sketch.add_line(4, 0, 4, 3)
    sketch.add_line(4, 3, 0, 3)

    assert sketch.profiles.count == 0


def test_arc_gap_leaves_the_loop_open(fusion):
    sketch = _sketch(fusion)
    # A rectangle whose last side is an arc that stops short of the start.
    sketch.sketchCurves.addLine(Point3D.create(0, 0), Point3D.create(4, 0))
    sketch.sketchCurves.addLine(Point3D.create(4, 0), Point3D.create(4, 3))
    sketch.sketchCurves.addLine(Point3D.create(4, 3), Point3D.create(0, 3))
    # Gap: the arc ends at (0.5, 0) instead of chaining back to (0, 0).
    sketch.sketchCurves.addArc(Point3D.create(0, 3), Point3D.create(0.5, 0))

    assert sketch.profiles.count == 0


def test_two_unconnected_lines_yield_no_profile(fusion):
    sketch = _sketch(fusion)
    sketch.add_line(0, 0, 1, 0)
    sketch.add_line(5, 5, 6, 5)

    assert sketch.profiles.count == 0


# ── Recompute and timeline indices ──────────────────────────────────────────


def test_compute_all_moves_timeline_indices(fusion):
    profile = _rect(fusion, 2.0, 2.0)
    first = _extrude(fusion, profile, 1.0, "Extrude1")
    second = _extrude(fusion, profile, 2.0, "Extrude2")

    timeline = fusion.design.timeline
    assert [first.timelineIndex, second.timelineIndex] == [0, 1]
    assert timeline.markerIndex == 2

    # Reorder a feature into the middle of the timeline and leave its stored
    # index stale, as an edit does before the model recomputes.  computeAll
    # must re-derive every index from the new order.
    middle = _extrude(fusion, profile, 3.0, "ExtrudeMiddle")
    timeline._features.insert(1, timeline._features.pop())  # move `middle` to index 1
    middle.timelineIndex = 99

    assert fusion.design.computeAll() is True

    positions = {feature.name: feature.timelineIndex for feature in timeline._features}
    assert positions == {"Extrude1": 0, "ExtrudeMiddle": 1, "Extrude2": 2}
    # The edit marker tracks the recomputed end of the timeline.
    assert timeline.markerIndex == 3


def test_compute_all_reports_changed_features_and_volume(fusion):
    feature = _extrude(fusion, _rect(fusion, 2.0, 2.0), 1.0, "Extrude1")

    assert feature.body.volume == 4.0  # 2 cm x 2 cm footprint x 1 cm depth

    # Widen the extrude distance: a recompute must pick up the new volume and
    # count this feature as changed.
    feature.body._distance = 5.0
    assert fusion.design.computeAll() is True

    assert fusion.design.recomputedFeatureCount == 1
    assert feature.body.volume == 20.0


def test_compute_all_reports_zero_changes_when_nothing_is_dirty(fusion):
    # A recompute with no edits still runs and reports zero changes rather than
    # pretending work happened.
    fusion.user_parameters.add("width", _value_input("10 mm"), "mm", "")
    assert fusion.design.computeAll() is True
    assert fusion.design.recomputedFeatureCount == 0


# ── Expression engine: unit folding ─────────────────────────────────────────


def test_expression_folds_millimetres_to_centimetres(fusion):
    parameter = fusion.user_parameters.add("length", _value_input("25 mm"), "mm", "")
    # Internal length unit is centimetres: 25 mm -> 2.5 cm.
    assert parameter.value == 2.5


def test_expression_folds_every_supported_length_unit(fusion):
    for expression, expected in (
        ("10 mm", 1.0),
        ("1 cm", 1.0),
        ("1 m", 100.0),
        ("1 in", 2.54),
        ("1 ft", 30.48),
    ):
        parameter = fusion.user_parameters.add(
            f"u_{expression.replace(' ', '_')}", _value_input(expression), "mm", ""
        )
        assert parameter.value == expected, expression


def test_expression_resolves_parameter_references(fusion):
    fusion.user_parameters.add("width", _value_input("40 mm"), "mm", "")
    half = fusion.user_parameters.add("half", _value_input("width / 2"), "mm", "")

    # 40 mm -> 4.0 cm, halved -> 2.0 cm.
    assert half.value == 2.0


def test_expression_rejects_unknown_names(fusion):
    with pytest.raises(KeyError):
        evaluate_expression("no_such_parameter / 2", fusion.design._resolve_parameter)


def test_expression_unit_folding_does_not_corrupt_bare_numbers(fusion):
    # A unitless expression must evaluate unchanged, not be scaled.
    parameter = fusion.user_parameters.add("count", _value_input("7"), "ul", "")
    assert parameter.value == 7.0


# ── Facade wiring ───────────────────────────────────────────────────────────


def test_make_fusion_defaults_to_one_design_document():
    fusion = make_fusion()
    assert fusion.document is not None
    assert fusion.document.name == "Test Design"
    assert fusion.design is not None


def test_make_fusion_without_document_is_the_cold_start_state():
    fusion = make_fusion(with_document=False)
    assert fusion.document is None
    assert fusion.design is None
    assert fusion.user_parameters is None
