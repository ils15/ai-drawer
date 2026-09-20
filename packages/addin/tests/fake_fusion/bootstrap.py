"""Install the fake ``adsk`` runtime by *in-place attribute mutation*.

The modules ``adsk``, ``adsk.core`` and ``adsk.fusion`` already exist in
``sys.modules`` (the shared test bootstrap installs a minimal mock).  This
module swaps their attributes in place -- it never replaces the module objects.

The distinction matters: ``dispatch.py`` does ``import adsk.core`` at import
time, so a module *replacement* only takes effect if the replacement happens
before ``dispatch`` is first imported.  Attribute mutation works in any import
order, because ``adsk.core.Application.get()`` is resolved at *call* time and
``adsk.core.DocumentTypes.FusionDesignDocumentType`` is a plain attribute read.

Install/uninstall is fully symmetric, so a fixture can save and restore the
exact module state around one test.
"""

from __future__ import annotations

import pathlib
import sys

from . import features, geometry, values
from .application import ApplicationClass
from .design import (
    FakeConstructionAxis,
    FakeConstructionPlane,
    FakeDesign,
    FakeOccurrence,
    FakeOccurrences,
)
from .factory import FakeFusion, make_fusion
from .features import (
    FakeChamferFeatures,
    FakeCircularPatternFeatures,
    FakeFilletFeatures,
    FakeHoleFeatures,
    FakeMeasureManager,
    FakeMeasureResults,
    FakeRectangularPatternFeatures,
)

_TESTS_DIR = pathlib.Path(__file__).resolve().parents[1]

_MISSING = object()
_SAVED: list[tuple[object, dict[str, object]]] = []
_INSTALLED: FakeFusion | None = None

_CORE_ATTRIBUTES = {
    "Application": ApplicationClass,
    "LogLevels": values.LogLevels,
    "LogTypes": values.LogTypes,
    "CustomEventHandler": values.CustomEventHandler,
    "Event": values.Event,
    "ValueInput": values.ValueInput,
    "ObjectCollection": values.ObjectCollection,
    "Matrix3D": values.Matrix3D,
    "Point3D": values.Point3D,
    "Vector3D": values.Vector3D,
    "Point2D": values.Point2D,
    "BoundingBox3D": values.BoundingBox3D,
    "DocumentTypes": values.DocumentTypes,
    "ViewOrientations": values.ViewOrientations,
    "CameraTypes": values.CameraTypes,
    "SaveImageFileOptions": values.SaveImageFileOptions,
    "MaterialLibraries": features.FakeMaterialLibraries,
    "MaterialLibrary": features.FakeMaterialLibrary,
    "Appearances": features.FakeAppearances,
    "Appearance": features.FakeAppearance,
    # Measurement: reached as app.measureManager and returned by its methods.
    "MeasureManager": FakeMeasureManager,
    "MeasureResults": FakeMeasureResults,
}

_FUSION_ATTRIBUTES = {
    "Design": FakeDesign,
    "DesignTypes": values.DesignTypes,
    "DistanceUnits": values.DistanceUnits,
    "MeshRefinementSettings": values.MeshRefinementSettings,
    "FeatureOperations": values.FeatureOperations,
    # The inspection tools read these enumerations directly
    # (adsk.fusion.SurfaceTypes.*, adsk.fusion.FeatureHealthStates.*), so they
    # must exist on the installed fake just as on the real module.
    "SurfaceTypes": values.SurfaceTypes,
    "FeatureHealthStates": values.FeatureHealthStates,
    # The feature tools read these enumerations directly (adsk.fusion.ExtentDirections.*),
    # so they must exist on the installed fake just as on the real module.
    "ExtentDirections": values.ExtentDirections,
    "PatternDistanceType": values.PatternDistanceType,
    # Extent definitions are constructed by static create() calls.
    "DistanceExtentDefinition": features.FakeDistanceExtentDefinition,
    "ThroughAllExtentDefinition": features.FakeThroughAllExtentDefinition,
    # Transient solid primitives, reached through TemporaryBRepManager.get().
    "TemporaryBRepManager": features.FakeTemporaryBRepManager,
    "TemporaryBRepBody": features.FakeTemporaryBRepBody,
    # Feature collection classes are reached through Component.features, but
    # pinning them here keeps the class-level surface honest for the pin check.
    "FilletFeatures": FakeFilletFeatures,
    "ChamferFeatures": FakeChamferFeatures,
    "HoleFeatures": FakeHoleFeatures,
    "RectangularPatternFeatures": FakeRectangularPatternFeatures,
    "CircularPatternFeatures": FakeCircularPatternFeatures,
    "ExtrudeFeatures": features.FakeExtrudeFeatures,
    "RevolveFeatures": features.FakeRevolveFeatures,
    "BaseFeatures": features.FakeBaseFeatures,
    "ExtrudeFeatureInput": features.FakeExtrudeFeatureInput,
    "RevolveFeatureInput": features.FakeRevolveFeatureInput,
    "ConstructionPlane": FakeConstructionPlane,
    "ConstructionAxis": FakeConstructionAxis,
    "Occurrences": FakeOccurrences,
    "Occurrence": FakeOccurrence,
    "ExtrudeFeature": features.FakeBuiltFeature,
    "RevolveFeature": features.FakeBuiltFeature,
    "BaseFeature": features.FakeBaseFeature,
    "SketchCurves": geometry.FakeSketchCurves,
    "SketchLines": geometry.FakeSketchLines,
    "SketchCircles": geometry.FakeSketchCircles,
    "SketchArcs": geometry.FakeSketchArcs,
}


def _ensure_base_mock() -> dict:
    """Import the shared bootstrap so the minimal adsk mock exists."""
    if str(_TESTS_DIR) not in sys.path:
        sys.path.insert(0, str(_TESTS_DIR))
    import _fusion_test_bootstrap  # noqa: F401 (installs adsk mock + parent pkg)

    return _fusion_test_bootstrap._MOCK_APP_EVENTS


def _install_attributes(module_name: str, attributes: dict) -> None:
    """Swap ``attributes`` onto ``sys.modules[module_name]``, saving the old."""
    module = sys.modules[module_name]
    snapshot = {name: getattr(module, name, _MISSING) for name in attributes}
    _SAVED.append((module, snapshot))
    for name, value in attributes.items():
        setattr(module, name, value)


def install(fusion: FakeFusion | None = None) -> FakeFusion:
    """Install *fusion* (a fresh one by default) over the adsk modules."""
    global _INSTALLED
    events = _ensure_base_mock()
    if fusion is None:
        fusion = make_fusion()
    _INSTALLED = fusion
    # Point the fake Application at the bootstrap's shared custom-event
    # registry, so dispatch.py's fireCustomEvent reaches handlers registered
    # through either the base mock or this fake.
    fusion.events = events
    fusion.app._events = events
    ApplicationClass._bind(fusion.app)
    _install_attributes("adsk.core", _CORE_ATTRIBUTES)
    _install_attributes("adsk.fusion", _FUSION_ATTRIBUTES)
    return fusion


def uninstall() -> None:
    """Restore the exact adsk module state from before the last install."""
    global _INSTALLED
    while _SAVED:
        module, snapshot = _SAVED.pop()
        for name, old in snapshot.items():
            if old is _MISSING:
                module.__dict__.pop(name, None)
            else:
                setattr(module, name, old)
    ApplicationClass._bind(None)
    _INSTALLED = None


def is_installed() -> bool:
    return _INSTALLED is not None


def installed() -> FakeFusion | None:
    return _INSTALLED
