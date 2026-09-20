"""Fake sketches, sketch curves, and *real* profile closure detection.

The closure rule is geometric, not bookkeeping: a profile is closed iff its
curve endpoints chain into a loop.  Curves are clustered into vertices by
endpoint proximity (union-find over shared vertices), and a component is a
closed profile exactly when every vertex in it has degree two -- each curve
contributes one to its start vertex and one to its end vertex, so a degree-two
graph is a single cycle.  Anything else (a dangling endpoint, a "V", a chain
that does not return to its start) is open.

This exists because an open profile is the number-one sketch bug: the extrude
that consumes it silently fails or produces nothing, and a mock that just
records "a profile was added" reports success either way.  Here, adding two
unconnected lines yields zero profiles and any test that expects one fails.

Documented edge case: two loops touching at a single vertex (a figure-eight)
gives that vertex degree four and is reported open.  Real Fusion treats that as
ambiguous too; the fake takes the strict reading.
"""

from __future__ import annotations

import math

from .values import Point3D

_EPSILON = 1e-7  # cm; endpoints closer than this are the same vertex


class FakeSketchPoint:
    def __init__(self, geometry):
        self.geometry = geometry


class FakeSketchCurve:
    """A sketch curve that knows the two points it spans."""

    def __init__(self, start: Point3D, end: Point3D, kind: str = "line"):
        self.startSketchPoint = FakeSketchPoint(start)
        self.endSketchPoint = FakeSketchPoint(end)
        self.geometry = kind

    @property
    def start(self):
        return self.startSketchPoint.geometry

    @property
    def end(self):
        return self.endSketchPoint.geometry


class FakeSketchCurves:
    def __init__(self):
        self._items: list[FakeSketchCurve] = []

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def addLine(self, start, end):
        curve = FakeSketchCurve(start, end, "line")
        self._items.append(curve)
        return curve

    def addArc(self, start, end, center=None):
        del center
        curve = FakeSketchCurve(start, end, "arc")
        self._items.append(curve)
        return curve

    def addCircle(self, center, radius):
        # A circle is its own closed loop: start and end coincide at the
        # centre, which gives that single vertex degree two (one contribution
        # per curve end) and so reads as closed by the chaining detector.
        start = Point3D.create(center.x, center.y, center.z)
        end = Point3D.create(center.x, center.y, center.z)
        curve = FakeSketchCurve(start, end, "circle")
        curve.center = center
        curve.radius = float(radius)
        self._items.append(curve)
        return curve

    def __iter__(self):
        return iter(self._items)


class FakeSketchPoints:
    def __init__(self):
        self._items: list[FakeSketchPoint] = []

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def add(self, geometry):
        point = FakeSketchPoint(geometry)
        self._items.append(point)
        return point


class FakeProfile:
    """One closed chain of curves."""

    def __init__(self, curves):
        self.curves = list(curves)

    @property
    def boundingBox(self):
        xs, ys = [], []
        for curve in self.curves:
            for point in (curve.start, curve.end):
                xs.append(point.x)
                ys.append(point.y)
        return FakeBoundingBox(min(xs), min(ys), max(xs), max(ys))

    @property
    def area(self):
        """Polygon area of the loop (shoelace over chained endpoints)."""
        ordered = _order_loop(self.curves)
        if ordered is None:
            return 0.0
        total = 0.0
        for index, point in enumerate(ordered):
            nxt = ordered[(index + 1) % len(ordered)]
            total += point[0] * nxt[1] - nxt[0] * point[1]
        return abs(total) / 2.0


class FakeProfiles:
    """Lazy view of the closed profiles found in the sketch."""

    def __init__(self, sketch):
        self._sketch = sketch

    @property
    def _profiles(self):
        return find_closed_profiles(self._sketch.sketchCurves)

    @property
    def count(self):
        return len(self._profiles)

    def item(self, index):
        profiles = self._profiles
        return profiles[index] if 0 <= index < len(profiles) else None

    def __iter__(self):
        return iter(self._profiles)


class FakeBoundingBox:
    def __init__(self, min_x, min_y, max_x, max_y, min_z=0.0, max_z=0.0):
        self.minPoint = Point3D.create(min_x, min_y, min_z)
        self.maxPoint = Point3D.create(max_x, max_y, max_z)


class FakeSketch:
    def __init__(self, name="Sketch1"):
        self.name = name
        self.isVisible = True
        self.sketchCurves = FakeSketchCurves()
        self.sketchPoints = FakeSketchPoints()
        self.profiles = FakeProfiles(self)

    def add_line(self, x1, y1, x2, y2, z=0.0):
        """Test helper: add a line from two coordinate pairs."""
        return self.sketchCurves.addLine(
            Point3D.create(x1, y1, z), Point3D.create(x2, y2, z)
        )

    def add_circle(self, cx, cy, radius, z=0.0):
        """Test helper: add a circle from center and radius."""
        return self.sketchCurves.addCircle(Point3D.create(cx, cy, z), radius)


class FakeSketches:
    def __init__(self):
        self._items: list[FakeSketch] = []

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def add(self, name="Sketch1"):
        sketch = FakeSketch(name)
        self._items.append(sketch)
        return sketch

    def __iter__(self):
        return iter(self._items)


# ── Closure detection ───────────────────────────────────────────────────────


def _key(point) -> tuple[float, float, float]:
    return (point.x, point.y, point.z)


def find_closed_profiles(curves) -> list[FakeProfile]:
    """Return the closed profiles formed by *curves*, via endpoint chaining."""
    items = list(curves)
    if not items:
        return []

    # 1. Cluster endpoints into vertices.
    vertices: list[tuple[float, float, float]] = []

    def vertex(point):
        here = _key(point)
        for index, existing in enumerate(vertices):
            if all(math.isclose(a, b, abs_tol=_EPSILON) for a, b in zip(here, existing, strict=True)):
                return index
        vertices.append(here)
        return len(vertices) - 1

    edges = [(vertex(curve.start), vertex(curve.end)) for curve in items]

    # 2. Union curves that share a vertex into connected components.
    parent = list(range(len(items)))
    first_curve_at_vertex: dict[int, int] = {}
    for index, (start, end) in enumerate(edges):
        for vertex_index in (start, end):
            if vertex_index in first_curve_at_vertex:
                _union_index(parent, index, first_curve_at_vertex[vertex_index])
            else:
                first_curve_at_vertex[vertex_index] = index

    # 3. Vertex degree: one per curve end.  A component is a closed loop iff
    #    every vertex it touches has degree exactly two.
    degree: dict[int, int] = {}
    for start, end in edges:
        degree[start] = degree.get(start, 0) + 1
        degree[end] = degree.get(end, 0) + 1

    by_root: dict[int, list] = {}
    for index, curve in enumerate(items):
        by_root.setdefault(_find_index(parent, index), []).append(curve)

    open_roots = {
        _find_index(parent, first_curve_at_vertex[vertex_index])
        for vertex_index, deg in degree.items()
        if deg != 2
    }

    return [FakeProfile(group) for root, group in by_root.items() if root not in open_roots]


def _find_index(parent, index):
    root = index
    while parent[root] != root:
        root = parent[root]
    while parent[index] != root:
        parent[index], index = root, parent[index]
    return root


def _union_index(parent, a, b):
    ra, rb = _find_index(parent, a), _find_index(parent, b)
    if ra != rb:
        parent[rb] = ra


def _order_loop(curves):
    """Chain a closed component's endpoints into a cycle of vertex points."""
    remaining = list(curves)
    current = remaining.pop(0)
    points = [_key(current.start)]
    tail = current.end
    while remaining:
        for index, candidate in enumerate(remaining):
            if _near(tail, candidate.start):
                points.append(_key(candidate.start))
                tail = candidate.end
                remaining.pop(index)
                break
            if _near(tail, candidate.end):
                points.append(_key(candidate.end))
                tail = candidate.start
                remaining.pop(index)
                break
        else:
            return None
    return points if _near(tail, current.start) else None


def _near(a, b):
    return all(math.isclose(x, y, abs_tol=_EPSILON) for x, y in zip(_key(a), _key(b), strict=True))
