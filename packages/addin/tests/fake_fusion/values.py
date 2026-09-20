"""SDK value types, geometry constructors, and enum namespaces.

Every type here implements exactly the members pinned in :mod:`.surface` --
nothing extra.  An adsk method that does not exist in the real API must not
exist here either, or the fake would start silently agreeing with wrong
assumptions (see the module docstring in :mod:`.surface`).
"""

from __future__ import annotations

# ── Enum-like namespaces ─────────────────────────────────────────────────────
# The tools reach these as ``adsk.<ns>.<Class>.<Member>`` and compare values,
# so distinct ints per class are enough and read like the real wrapper.


def _enum(**members: int) -> type:
    """Build an enum-like namespace with one distinct int per member."""
    return type("Enum", (), dict(members, _members=tuple(members)))


class LogLevels:
    InfoLogLevel = 0
    ErrorLogLevel = 1
    WarningLogLevel = 2


class LogTypes:
    FileLogType = 0
    ConsoleLogType = 1


DocumentTypes = _enum(FusionDesignDocumentType=0)
DesignTypes = _enum(ParametricDesignType=0, DirectDesignType=1)
DistanceUnits = _enum(
    MillimeterDistanceUnits=0,
    CentimeterDistanceUnits=1,
    MeterDistanceUnits=2,
    InchDistanceUnits=3,
)
MeshRefinementSettings = _enum(MeshRefinementLow=0, MeshRefinementMedium=1, MeshRefinementHigh=2)
ViewOrientations = _enum(
    FrontViewOrientation=0,
    BackViewOrientation=1,
    LeftViewOrientation=2,
    RightViewOrientation=3,
    TopViewOrientation=4,
    BottomViewOrientation=5,
    IsoTopRightViewOrientation=6,
    IsoTopLeftViewOrientation=7,
    IsoBottomRightViewOrientation=8,
    IsoBottomLeftViewOrientation=9,
    ArbitraryViewOrientation=10,
)
CameraTypes = _enum(
    OrthographicCameraType=0,
    PerspectiveCameraType=1,
    PerspectiveWithOrthoFacesCameraType=2,
)
# Values follow the published Autodesk enumerators (see fusion_PatternDistanceType
# and fusion_ExtentDirections): the pattern tools read them by name, and the
# numeric values must not drift from the real runtime.
PatternDistanceType = _enum(ExtentPatternDistanceType=0, SpacingPatternDistanceType=1)
ExtentDirections = _enum(
    PositiveExtentDirection=0,
    NegativeExtentDirection=1,
    SymmetricExtentDirection=2,
)
# How a feature's new geometry combines with the existing bodies; the published
# enumerator order (see fusion_FeatureOperations) is NewBody, Join, Cut,
# Intersect, NewComponent.
FeatureOperations = _enum(
    NewBodyFeatureOperation=0,
    JoinFeatureOperation=1,
    CutFeatureOperation=2,
    IntersectFeatureOperation=3,
    NewComponentFeatureOperation=4,
)


# ── Event plumbing ───────────────────────────────────────────────────────────


class CustomEventHandler:
    """Subclassable hook, mirroring ``adsk.core.CustomEventHandler``."""

    def notify(self, args):
        """Called by the runtime when the event fires."""


class Event:
    def __init__(self):
        self._handlers = []

    def add(self, handler):
        if handler not in self._handlers:
            self._handlers.append(handler)
        return True

    def remove(self, handler):
        if handler in self._handlers:
            self._handlers.remove(handler)
        return True

    def notify_handlers(self, args=None):
        for handler in list(self._handlers):
            handler.notify(args)


# ── Geometry and value containers ───────────────────────────────────────────


class _XYZ:
    """Point/vector base: three mutable coordinates, like the real wrapper."""

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = x
        self.y = y
        self.z = z

    def as_tuple(self):
        return (self.x, self.y, self.z)

    def __eq__(self, other):
        if isinstance(other, _XYZ):
            return self.as_tuple() == other.as_tuple()
        return NotImplemented

    def __repr__(self):
        return f"{type(self).__name__}({self.x}, {self.y}, {self.z})"


class Point3D(_XYZ):
    @staticmethod
    def create(x=0.0, y=0.0, z=0.0):
        return Point3D(x, y, z)


class Vector3D(_XYZ):
    @staticmethod
    def create(x=0.0, y=0.0, z=0.0):
        return Vector3D(x, y, z)


class Point2D:
    def __init__(self, x=0.0, y=0.0):
        self.x = x
        self.y = y

    @staticmethod
    def create(x=0.0, y=0.0):
        return Point2D(x, y)


class Matrix3D:
    @staticmethod
    def create():
        return Matrix3D()

    def __init__(self):
        self._data = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


class BoundingBox3D:
    """``adsk.core.BoundingBox3D``: an axis-aligned span between two points."""

    @staticmethod
    def create(min_point, max_point):
        return BoundingBox3D(min_point, max_point)

    def __init__(self, min_point, max_point):
        self.minPoint = min_point
        self.maxPoint = max_point


class ObjectCollection:
    @staticmethod
    def create():
        return ObjectCollection()

    def __init__(self):
        self._items: list = []

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def add(self, item):
        self._items.append(item)

    def __iter__(self):
        return iter(self._items)


class ValueInput:
    """Opaque constructor argument for ``UserParameters.add``.

    ``createByString`` carries a Fusion *expression* (``"25 mm"``); the
    expression engine turns it into a value.  ``createByReal`` carries a plain
    number already in internal units.
    """

    def __init__(self, expression=None, real=None):
        self.expression = expression
        self.real = real

    @staticmethod
    def createByString(expression):
        return ValueInput(expression=str(expression))

    @staticmethod
    def createByReal(value):
        return ValueInput(real=float(value))


class SaveImageFileOptions:
    @staticmethod
    def create(filename):
        return SaveImageFileOptions(filename)

    def __init__(self, filename):
        self.filename = filename
        self.width = 0
        self.height = 0
        self.isBackgroundTransparent = False
        self.isAntiAliased = True
