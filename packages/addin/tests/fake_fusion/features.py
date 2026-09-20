"""Fake feature collections that compute a body and a bounding box.

A feature here is an extrude: it consumes a closed profile and a distance and
produces a solid body whose bounding box is the profile's footprint swept by
the distance.  Keeping the geometry real (instead of recording "a body was
created") means a test can assert the parameter-driven dimension actually moved
after ``computeAll`` -- the whole point of the recompute path.
"""

from __future__ import annotations

from .values import Point3D


class FakeMaterial:
    def __init__(self, name="Steel"):
        self.name = name


class FakeBoundingBox3D:
    def __init__(self, min_point, max_point):
        self.minPoint = min_point
        self.maxPoint = max_point


class FakeBRepBody:
    def __init__(self, name, profile, distance):
        self.name = name
        self.isSolid = True
        self.isVisible = True
        self.material = FakeMaterial()
        self._profile = profile
        self._distance = distance
        self._recompute()

    def _recompute(self):
        box = self._profile.boundingBox
        self.boundingBox = FakeBoundingBox3D(
            Point3D.create(box.minPoint.x, box.minPoint.y, 0.0),
            Point3D.create(box.maxPoint.x, box.maxPoint.y, self._distance),
        )
        self.volume = (
            (self._profile.area or 0.0) * abs(self._distance)
        )

    @property
    def objectType(self):
        return "adsk.fusion.BRepBody"


class FakeBRepBodies:
    def __init__(self):
        self._items: list[FakeBRepBody] = []

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def add(self, body):
        self._items.append(body)
        return body

    def __iter__(self):
        return iter(self._items)


class FakeFeature:
    """One timeline entry.  ``timelineIndex`` is its position in the design."""

    def __init__(self, name, kind, body):
        self.name = name
        self.kind = kind
        self.body = body
        self.timelineIndex = 0

    def _recompute(self):
        self.body._recompute()

    @property
    def objectType(self):
        return f"adsk.fusion.{self.kind}Feature"


class FakeFeatures:
    def __init__(self, timeline):
        self._items: list[FakeFeature] = []
        self._timeline = timeline

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def add_extrude(self, profile, distance, name="Extrude1"):
        """Create an extrude feature over a closed profile."""
        if profile is None:
            raise ValueError("extrude requires a closed profile")
        body = FakeBRepBody(name, profile, distance)
        feature = FakeFeature(name, "Extrude", body)
        self._items.append(feature)
        self._timeline._append_feature(feature)
        return feature

    def _recompute_all(self):
        changed = 0
        for feature in self._items:
            before = feature.body.volume
            feature._recompute()
            if feature.body.volume != before:
                changed += 1
        return changed

    def __iter__(self):
        return iter(self._items)
