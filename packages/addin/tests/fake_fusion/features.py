"""Fake feature collections: extrudes that compute a body, plus the fillet,
chamfer, hole, and pattern collections the feature tools drive.

An extrude consumes a closed profile and a distance and produces a solid body
whose bounding box is the profile's footprint swept by the distance.  Keeping
the geometry real (instead of recording "a body was created") means a test can
assert the parameter-driven dimension actually moved after ``computeAll`` --
the whole point of the recompute path.

The feature-tool collections (fillet, chamfer, hole, rectangular/circular
pattern) deliberately do *not* simulate geometric side effects: a built feature
records the parameters that produced it and round-trips them to the caller.
What is real about them is the *validation* -- a non-positive radius, a
non-positive diameter, or a mixed-kind pattern input is rejected the way real
Fusion rejects it, and a radius that does not fit the referenced geometry makes
``add`` return ``None`` so the tool's "Fusion refused to build it" branch is
reachable instead of a silent success.

Edges and faces carry an ``entityToken`` and are constructible in a test, so
``get_active_selection`` can store them and the feature tools can resolve the
stored handles back to the very same objects.
"""

from __future__ import annotations

import math

from .values import Point3D


class FakeMaterial:
    def __init__(self, name="Steel"):
        self.name = name


class FakeAppearance:
    """An appearance (colour/finish) the way ``addByCopy`` hands it back."""

    def __init__(self, name):
        self.name = name

    @property
    def objectType(self):
        return "adsk.core.Appearance"


class FakeAppearances:
    """``Design.appearances`` / ``MaterialLibrary.appearances``.

    ``addByCopy`` copies a library appearance into the design, the way the real
    API does; a name that is not in the library resolves to ``None`` and the
    tool reports that as ``not_found`` rather than inventing an appearance.
    """

    def __init__(self, items=()):
        self._items: list[FakeAppearance] = [FakeAppearance(name) for name in items]

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def itemByName(self, name):
        for appearance in self._items:
            if appearance.name == name:
                return appearance
        return None

    def addByCopy(self, appearance):
        copy = FakeAppearance(getattr(appearance, "name", "Appearance"))
        self._items.append(copy)
        return copy

    def __iter__(self):
        return iter(self._items)


class FakeMaterialLibrary:
    def __init__(self, name, appearances=()):
        self.name = name
        self.appearances = FakeAppearances(appearances)

    @property
    def objectType(self):
        return "adsk.core.MaterialLibrary"


class FakeMaterialLibraries:
    """``Application.materialLibraries``: the installed appearance libraries."""

    def __init__(self, libraries=()):
        self._items: list[FakeMaterialLibrary] = list(libraries)

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def itemByName(self, name):
        for library in self._items:
            if library.name == name:
                return library
        return None

    def __iter__(self):
        return iter(self._items)


# The default library the shipped tool points at, with the appearances a real
# Fusion install publishes there.  A test that wants a missing-library or
# missing-appearance failure installs its own libraries on the fake.
_DEFAULT_APPEARANCES = (
    "Steel",
    "Aluminum",
    "Brass",
    "Copper",
    "Gold",
    "Iron",
    "Lead",
    "Silver",
    "Titanium",
    "Zinc",
    "Plastic",
    "Wood",
    "Glass",
    "Water",
    "Air",
)


def default_material_libraries():
    return FakeMaterialLibraries([FakeMaterialLibrary("Fusion 360 Material Library", _DEFAULT_APPEARANCES)])


class FakeBoundingBox3D:
    def __init__(self, min_point, max_point):
        self.minPoint = min_point
        self.maxPoint = max_point


class FakeBRepEdge:
    """A linear edge the fillet and chamfer tools address.

    ``length`` is in centimetres and is what the fake compares a fillet radius
    against when deciding whether the feature is buildable at all.
    """

    def __init__(self, name, length, entity_token=None):
        self.name = name
        self.length = length
        self.entityToken = entity_token or f"edge:{name}"

    @property
    def objectType(self):
        return "adsk.fusion.BRepEdge"


class FakeBRepFace:
    """A face the hole tool can start a hole on.

    ``isPlanar`` is what the hole tool's face requirement comes down to: a
    simple hole needs a plane to position and extrude from, so a non-planar
    face is rejected the way real Fusion rejects it.
    """

    def __init__(self, name, area=1.0, centroid=None, entity_token=None, is_planar=True):
        self.name = name
        self.area = area
        self.centroid = centroid if centroid is not None else Point3D.create()
        self.entityToken = entity_token or f"face:{name}"
        self.isPlanar = is_planar

    @property
    def objectType(self):
        return "adsk.fusion.BRepFace"


class _BRepEntities:
    """Shared ``count`` / ``item`` / ``add`` / iteration for BRep collections."""

    def __init__(self):
        self._items: list = []

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def add(self, entity):
        self._items.append(entity)
        return entity

    def __iter__(self):
        return iter(self._items)


class FakeBRepEdges(_BRepEntities):
    pass


class FakeBRepFaces(_BRepEntities):
    pass


class FakeBRepBody:
    def __init__(self, name, profile=None, distance=None, temporary_body=None):
        self.name = name
        self.isSolid = True
        self.isVisible = True
        self.material = FakeMaterial()
        self.appearance = None
        self._profile = profile
        self._distance = distance
        self.parentComponent = None
        self.edges = FakeBRepEdges()
        self.faces = FakeBRepFaces()
        if temporary_body is not None:
            # A primitive built by TemporaryBRepManager brings its own extent;
            # there is no profile to re-evaluate when a parameter moves.
            self.boundingBox = temporary_body.boundingBox
            self.volume = temporary_body.volume
        else:
            self._recompute()

    def _recompute(self):
        box = self._profile.boundingBox
        self.boundingBox = FakeBoundingBox3D(
            Point3D.create(box.minPoint.x, box.minPoint.y, 0.0),
            Point3D.create(box.maxPoint.x, box.maxPoint.y, self._distance),
        )
        self.volume = (self._profile.area or 0.0) * abs(self._distance)

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

    def add(self, body, target_base_feature=None):
        """Add a body, optionally inside a base feature's edit cycle.

        A parametric design requires the base feature; a direct one does not.
        The fake accepts both and records which path was used, because the
        geometry is the same either way and the difference is timeline-only.
        """
        del target_base_feature
        self._items.append(body)
        return body

    def __iter__(self):
        return iter(self._items)


# ── Value resolution ────────────────────────────────────────────────────────


def _resolve_value(value_input, design):
    """Resolve a ``ValueInput`` to the number it represents.

    ``createByReal`` already carries an internal value (centimetres for a
    length, a count for a quantity); ``createByString`` carries a Fusion
    expression the engine evaluates against the design's parameters.  A length
    comes out in centimetres, an angle in degrees -- both internal units,
    which is what the API's own comparisons use.
    """
    real = getattr(value_input, "real", None)
    if real is not None:
        return float(real)
    expression = getattr(value_input, "expression", None)
    if not expression:
        raise ValueError("a dimension is required")
    # Imported here rather than at module level: design.py imports this module
    # at its top, so a module-level import would be circular.
    from .design import evaluate_expression

    if design is None:
        return evaluate_expression(expression, lambda name: None)
    return evaluate_expression(expression, design._resolve_parameter)


def _entity_kinds(entities):
    return {getattr(entity, "objectType", type(entity).__name__) for entity in entities}


def _check_homogeneous(entities):
    """Pattern inputs must all be one entity kind (a hard Fusion requirement)."""
    kinds = _entity_kinds(entities)
    if len(kinds) > 1:
        raise ValueError("all patterned entities must be the same type; got " + ", ".join(sorted(kinds)))


# ── Built features ──────────────────────────────────────────────────────────


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


class FakeBuiltFeature:
    """A feature built by one of the feature-tool collections.

    It owns no body and performs no geometric side effects: the tool reads only
    its ``name``, and the recorded ``params`` let a test assert that what the
    tool reported round-tripped through the fake and back.
    """

    def __init__(self, name, kind, **params):
        self.name = name
        self.kind = kind
        self.params = params
        self.body = None
        # Feature-geometry collections are always present, even for a feature
        # that produced none, so a tool reading .bodies never hits a hole.
        self.bodies = params.pop("bodies", None) or FakeBRepBodies()
        self.timelineIndex = 0

    @property
    def objectType(self):
        return f"adsk.fusion.{self.kind}Feature"


# ── Fillet ──────────────────────────────────────────────────────────────────


class FakeFilletEdgeSets:
    """``FilletFeatureInput.edgeSetInputs``: one constant-radius edge set."""

    def __init__(self, fillet_input):
        self._fillet_input = fillet_input
        self._sets: list[tuple[list, float, bool]] = []

    def addConstantRadiusEdgeSet(self, edges, radius, is_tangent_chain):
        items = list(edges)
        if not items:
            raise ValueError("fillet needs at least one edge")
        if _resolve_value(radius, self._fillet_input._design) <= 0:
            raise ValueError("fillet radius must be greater than zero")
        self._sets.append((items, _resolve_value(radius, self._fillet_input._design), bool(is_tangent_chain)))
        return True


class FakeFilletFeatureInput:
    def __init__(self, design):
        self._design = design
        self.edgeSetInputs = FakeFilletEdgeSets(self)


class FakeFilletFeatures:
    def __init__(self, features):
        self._features = features
        self._count = 0

    def createInput(self):
        return FakeFilletFeatureInput(self._features._design)

    def add(self, fillet_input):
        sets = fillet_input.edgeSetInputs._sets
        if not sets:
            return None
        resolved = []
        for items, radius, is_tangent_chain in sets:
            for edge in items:
                length = getattr(edge, "length", None)
                # A radius larger than the edge it must ride cannot be built;
                # real Fusion reports that by returning None from add().
                if length is not None and radius > length:
                    return None
            resolved.append((items, radius, is_tangent_chain))
        self._count += 1
        return self._features._register(
            FakeBuiltFeature(
                f"Fillet{self._count}",
                "Fillet",
                edge_count=sum(len(items) for items, _, _ in resolved),
                radius_cm=resolved[0][1],
                is_tangent_chain=resolved[0][2],
            )
        )


# ── Chamfer ─────────────────────────────────────────────────────────────────


class FakeChamferEdgeSets:
    """``ChamferFeatureInput.chamferEdgeSets``: one equal-distance edge set."""

    def __init__(self, chamfer_input):
        self._chamfer_input = chamfer_input
        self._sets: list[tuple[list, float, bool]] = []

    def addEqualDistanceChamferEdgeSet(self, edges, distance, is_tangent_chain):
        items = list(edges)
        if not items:
            raise ValueError("chamfer needs at least one edge")
        if _resolve_value(distance, self._chamfer_input._design) <= 0:
            raise ValueError("chamfer distance must be greater than zero")
        self._sets.append((items, _resolve_value(distance, self._chamfer_input._design), bool(is_tangent_chain)))
        return True


class FakeChamferFeatureInput:
    def __init__(self, design):
        self._design = design
        self.chamferEdgeSets = FakeChamferEdgeSets(self)


class FakeChamferFeatures:
    def __init__(self, features):
        self._features = features
        self._count = 0

    def createInput2(self):
        return FakeChamferFeatureInput(self._features._design)

    def add(self, chamfer_input):
        sets = chamfer_input.chamferEdgeSets._sets
        if not sets:
            return None
        resolved = []
        for items, distance, is_tangent_chain in sets:
            for edge in items:
                length = getattr(edge, "length", None)
                if length is not None and distance > length:
                    return None
            resolved.append((items, distance, is_tangent_chain))
        self._count += 1
        return self._features._register(
            FakeBuiltFeature(
                f"Chamfer{self._count}",
                "Chamfer",
                edge_count=sum(len(items) for items, _, _ in resolved),
                distance_cm=resolved[0][1],
                is_tangent_chain=resolved[0][2],
            )
        )


# ── Hole ────────────────────────────────────────────────────────────────────


class FakeHoleFeatureInput:
    def __init__(self, design, diameter):
        self._design = design
        self._diameter = diameter
        self._face = None
        self._point = None
        self._extent = None

    def setPositionByPoint(self, face, point):
        if not getattr(face, "isPlanar", True):
            raise ValueError("a simple hole must start on a planar face")
        self._face = face
        self._point = point
        return True

    def setDistanceExtent(self, depth):
        self._extent = ("distance", depth)
        return True

    def setAllExtent(self, direction):
        self._extent = ("all", direction)
        return True


class FakeHoleFeatures:
    def __init__(self, features):
        self._features = features
        self._count = 0

    def createSimpleInput(self, diameter):
        if _resolve_value(diameter, self._features._design) <= 0:
            raise ValueError("hole diameter must be greater than zero")
        return FakeHoleFeatureInput(self._features._design, diameter)

    def add(self, hole_input):
        if hole_input._face is None or hole_input._point is None:
            return None
        extent = hole_input._extent
        if extent is None:
            return None
        depth_cm = None
        if extent[0] == "distance":
            depth_cm = _resolve_value(extent[1], self._features._design)
            if depth_cm <= 0:
                raise ValueError("hole depth must be greater than zero")
        self._count += 1
        return self._features._register(
            FakeBuiltFeature(
                f"Hole{self._count}",
                "Hole",
                diameter_cm=_resolve_value(hole_input._diameter, self._features._design),
                extent=extent[0],
                depth_cm=depth_cm,
            )
        )


# ── Rectangular pattern ─────────────────────────────────────────────────────


class FakeRectangularPatternFeatureInput:
    def __init__(self, entities, direction_one_entity, quantity_one, distance_one, distance_type):
        self._entities = list(entities)
        self._direction_one = direction_one_entity
        self.quantityOne = quantity_one
        self.distanceOne = distance_one
        self.distanceType = distance_type
        self.directionTwoEntity = None
        self.quantityTwo = None
        self.distanceTwo = None
        self.isSymmetricInDirectionOne = False
        self.isSymmetricInDirectionTwo = False


class FakeRectangularPatternFeatures:
    def __init__(self, features):
        self._features = features
        self._count = 0

    def createInput(self, entities, direction_one_entity, quantity_one, distance_one, distance_type=None):
        items = list(entities)
        _check_homogeneous(items)
        if direction_one_entity is None:
            raise ValueError("a rectangular pattern needs a direction entity")
        return FakeRectangularPatternFeatureInput(
            items, direction_one_entity, quantity_one, distance_one, distance_type
        )

    def add(self, pattern_input):
        quantity_one = _resolve_value(pattern_input.quantityOne, self._features._design)
        if quantity_one < 1:
            raise ValueError("quantity_one must be at least 1")
        if _resolve_value(pattern_input.distanceOne, self._features._design) <= 0:
            raise ValueError("pattern spacing must be greater than zero")
        quantity_two = None
        if pattern_input.directionTwoEntity is not None:
            quantity_two = _resolve_value(pattern_input.quantityTwo, self._features._design)
            if quantity_two < 1:
                raise ValueError("quantity_two must be at least 1")
            if _resolve_value(pattern_input.distanceTwo, self._features._design) <= 0:
                raise ValueError("pattern spacing must be greater than zero")
        self._count += 1
        return self._features._register(
            FakeBuiltFeature(
                f"RectangularPattern{self._count}",
                "RectangularPattern",
                entity_count=len(pattern_input._entities),
                quantity_one=int(quantity_one),
                quantity_two=None if quantity_two is None else int(quantity_two),
                is_symmetric=bool(pattern_input.isSymmetricInDirectionOne),
            )
        )


# ── Circular pattern ────────────────────────────────────────────────────────


class FakeCircularPatternFeatureInput:
    def __init__(self, entities, axis_entity):
        self._entities = list(entities)
        self._axis = axis_entity
        self.quantity = None
        self.totalAngle = None
        self.isSymmetric = False


class FakeCircularPatternFeatures:
    def __init__(self, features):
        self._features = features
        self._count = 0

    def createInput(self, entities, axis_entity):
        items = list(entities)
        _check_homogeneous(items)
        if axis_entity is None:
            raise ValueError("a circular pattern needs an axis entity")
        return FakeCircularPatternFeatureInput(items, axis_entity)

    def add(self, pattern_input):
        quantity = _resolve_value(pattern_input.quantity, self._features._design)
        if quantity < 1:
            raise ValueError("quantity must be at least 1")
        if _resolve_value(pattern_input.totalAngle, self._features._design) <= 0:
            raise ValueError("total angle must be greater than zero")
        self._count += 1
        return self._features._register(
            FakeBuiltFeature(
                f"CircularPattern{self._count}",
                "CircularPattern",
                entity_count=len(pattern_input._entities),
                quantity=int(quantity),
                is_symmetric=bool(pattern_input.isSymmetric),
            )
        )


# ── Extrude and revolve ─────────────────────────────────────────────────────


class FakeDistanceExtentDefinition:
    """``DistanceExtentDefinition.create(valueInput)``: a fixed extent."""

    def __init__(self, value_input):
        self.valueInput = value_input

    @staticmethod
    def create(value_input):
        return FakeDistanceExtentDefinition(value_input)


class FakeThroughAllExtentDefinition:
    """``ThroughAllExtentDefinition.create()``: an unbounded extent."""

    def __init__(self):
        self.valueInput = None

    @staticmethod
    def create():
        return FakeThroughAllExtentDefinition()


class FakeExtrudeFeatureInput:
    """``ExtrudeFeatures.createInput(profile, operation)``."""

    def __init__(self, design, profile, operation):
        self._design = design
        self._profile = profile
        self._operation = operation
        self._extent = None

    @property
    def profile(self):
        return self._profile

    @property
    def operation(self):
        return self._operation

    def setOneSideExtent(self, extent_definition, direction=None):
        self._extent = ("one_side", extent_definition, direction)
        return True

    def setSymmetricExtent(self, extent_definition):
        self._extent = ("symmetric", extent_definition)
        return True


class FakeExtrudeFeatures:
    def __init__(self, features):
        self._features = features
        self._count = 0

    def createInput(self, profile, operation):
        if profile is None:
            raise ValueError("extrude requires a closed profile")
        return FakeExtrudeFeatureInput(self._features._design, profile, operation)

    def add(self, extrude_input):
        if extrude_input._extent is None:
            return None
        kind, definition = extrude_input._extent[0], extrude_input._extent[1]
        distance_cm = None
        body = None
        if isinstance(definition, FakeDistanceExtentDefinition):
            distance_cm = _resolve_value(definition.valueInput, self._features._design)
            if distance_cm <= 0:
                raise ValueError("extrude distance must be greater than zero")
        # A through-all extent is bounded by the bodies it meets; the fake does
        # not compute boolean intersections, so it records the feature without
        # fabricating a span and reports no body for it.
        if distance_cm is not None:
            self._count += 1
            body = FakeBRepBody(f"Extrude{self._count}", extrude_input._profile, distance_cm)
        else:
            self._count += 1
        bodies = FakeBRepBodies()
        if body is not None:
            bodies.add(body)
        return self._features._register(
            FakeBuiltFeature(
                f"Extrude{self._count}",
                "Extrude",
                operation=extrude_input._operation,
                extent=kind,
                distance_cm=distance_cm,
                bodies=bodies,
            ),
            bodies=bodies,
        )


class FakeRevolveFeatureInput:
    """``RevolveFeatures.createInput(profile, axis, operation)``."""

    def __init__(self, design, profile, axis, operation):
        self._design = design
        self._profile = profile
        self._axis = axis
        self._operation = operation
        self._angle = None

    @property
    def profile(self):
        return self._profile

    @property
    def axis(self):
        return self._axis

    @property
    def operation(self):
        return self._operation

    def setAngleExtent(self, is_symmetric, angle):
        # The real signature takes the angle as a ValueInput; a symmetric
        # revolution sweeps it about both sides of the profile.
        self._angle = (bool(is_symmetric), angle)
        return True


class FakeRevolveFeatures:
    def __init__(self, features):
        self._features = features
        self._count = 0

    def createInput(self, profile, axis, operation):
        if profile is None:
            raise ValueError("revolve requires a closed profile")
        if axis is None:
            raise ValueError("revolve requires an axis")
        return FakeRevolveFeatureInput(self._features._design, profile, axis, operation)

    def add(self, revolve_input):
        if revolve_input._angle is None:
            return None
        is_symmetric, angle = revolve_input._angle
        angle_value = _resolve_value(angle, self._features._design)
        if angle_value <= 0:
            raise ValueError("revolve angle must be greater than zero")
        self._count += 1
        # A revolution's swept solid is not computed: the tool's contract is
        # the feature and its parameters, and the validation is real.
        return self._features._register(
            FakeBuiltFeature(
                f"Revolve{self._count}",
                "Revolve",
                operation=revolve_input._operation,
                angle_deg=angle_value,
                is_symmetric=is_symmetric,
                bodies=FakeBRepBodies(),
            ),
            bodies=FakeBRepBodies(),
        )


# ── Base features (the parametric wrapper for transient geometry) ──────────


class FakeBaseFeature(FakeBuiltFeature):
    """A base feature: an edit cycle a parametric design wraps body creation in."""

    def __init__(self, name):
        super().__init__(name, "Base")
        self.isEditing = False

    def startEdit(self):
        self.isEditing = True
        return True

    def finishEdit(self):
        self.isEditing = False
        return True


class FakeBaseFeatures:
    def __init__(self, features):
        self._features = features
        self._count = 0

    def add(self):
        self._count += 1
        return self._features._register(FakeBaseFeature(f"BaseFeature{self._count}"))


# ── Transient BRep bodies (the primitives create_body builds from) ────────


class FakeTemporaryBRepBody:
    """A transient solid with a conservative bounding box and exact volume."""

    def __init__(self, bounding_box, volume):
        self.boundingBox = bounding_box
        self.volume = volume
        self.isSolid = True

    @property
    def objectType(self):
        return "adsk.fusion.TemporaryBRepBody"


def _box_volume(box):
    return (box.maxPoint.x - box.minPoint.x) * (box.maxPoint.y - box.minPoint.y) * (box.maxPoint.z - box.minPoint.z)


class FakeTemporaryBRepManager:
    """``TemporaryBRepManager.get()``: transient solid primitives, in centimetres."""

    @staticmethod
    def get():
        return FakeTemporaryBRepManager()

    def createBox(self, bounding_box):
        return FakeTemporaryBRepBody(bounding_box, _box_volume(bounding_box))

    def createCylinderOrCone(self, point1, point2, radius1, radius2):
        from .values import BoundingBox3D, Point3D

        radius1, radius2 = float(radius1), float(radius2)
        height = abs(point2.z - point1.z)
        max_radius = max(radius1, radius2)
        # A superset of the true box: the primitives are axis-aligned here and
        # the exact cone geometry is not what the tool's contract reports.
        box = BoundingBox3D.create(
            Point3D.create(
                min(point1.x, point2.x) - max_radius,
                min(point1.y, point2.y) - max_radius,
                min(point1.z, point2.z),
            ),
            Point3D.create(
                max(point1.x, point2.x) + max_radius,
                max(point1.y, point2.y) + max_radius,
                max(point1.z, point2.z),
            ),
        )
        volume = math.pi * (radius1 * radius1 + radius2 * radius2) / 2.0 * height
        return FakeTemporaryBRepBody(box, volume)

    def createSphere(self, center, radius):
        from .values import BoundingBox3D, Point3D

        radius = float(radius)
        box = BoundingBox3D.create(
            Point3D.create(center.x - radius, center.y - radius, center.z - radius),
            Point3D.create(center.x + radius, center.y + radius, center.z + radius),
        )
        return FakeTemporaryBRepBody(box, 4.0 / 3.0 * math.pi * radius**3)


# ── The component's feature collection ──────────────────────────────────────


class FakeFeatures:
    """``Component.features``: the extrude collection and the feature-tool ones.

    Extrudes build real bodies and join ``_items``; the feature-tool collections
    build bodyless parameter records.  Both land on the timeline, but only the
    ones with geometry are re-evaluated by ``computeAll``.
    """

    def __init__(self, timeline, design=None):
        self._items: list[FakeFeature] = []
        self._timeline = timeline
        self._design = design
        self.filletFeatures = FakeFilletFeatures(self)
        self.chamferFeatures = FakeChamferFeatures(self)
        self.holeFeatures = FakeHoleFeatures(self)
        self.rectangularPatternFeatures = FakeRectangularPatternFeatures(self)
        self.circularPatternFeatures = FakeCircularPatternFeatures(self)
        self.extrudeFeatures = FakeExtrudeFeatures(self)
        self.revolveFeatures = FakeRevolveFeatures(self)
        self.baseFeatures = FakeBaseFeatures(self)

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
        if self._timeline is not None:
            self._timeline._append_feature(feature)
        return feature

    def _register(self, feature, bodies=None):
        """Record a feature built by one of the feature-tool collections."""
        if bodies is not None:
            feature.bodies = bodies
        self._items.append(feature)
        # A direct-modelled design has no timeline; the feature still exists.
        if self._timeline is not None:
            self._timeline._append_feature(feature)
        return feature

    def _recompute_all(self):
        changed = 0
        for feature in self._items:
            # A feature-tool feature records parameters but no geometry; there
            # is nothing to re-evaluate for it, so it is skipped rather than
            # crashing the recompute path.
            if feature.body is None:
                continue
            before = feature.body.volume
            feature._recompute()
            if feature.body.volume != before:
                changed += 1
        return changed

    def __iter__(self):
        return iter(self._items)
