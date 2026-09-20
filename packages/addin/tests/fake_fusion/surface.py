"""The pinned real-API surface the fake must implement.

This registry is the anti-drift contract between three things that must agree:

1.  what the shipped tools *call* (``adsk.core.X``, ``adsk.fusion.Y``),
2.  what the behavioral fake *implements*, and
3.  what Autodesk's published reference docs *document*.

If any two disagree, ``tests/test_api_surface_pin.py`` fails.  That is the
failure mode that shipped two broken community servers: faust's
``create_parameter`` called ``UserParameters.createInput()`` (does not exist)
and ndoo's screenshot tool used positional arguments that the real API rejects
-- both passed their own tests because their mocks *agreed* with the wrong
assumption.  A mock that implements more than the real API silently hides
exactly that class of bug, so the fake implements *only* what is pinned here.

Members are grouped by SDK namespace and class.  ``STATIC`` members are reached
as ``adsk.<ns>.<Class>.<member>`` at call time; the rest are instance members
reached through an object the tools already hold.
"""

# ── Namespace/class/member pins ─────────────────────────────────────────────

# static = reached as adsk.<ns>.<Class>.<member> without an instance.
PINNED_SURFACE: dict[str, dict[str, set[str]]] = {
    "core": {
        "Application": {
            "get",  # static
            "userInterface",
            "activeProduct",
            "activeDocument",
            "activeViewport",
            "documents",
            "version",
            "log",
            "registerCustomEvent",
            "fireCustomEvent",
            "unregisterCustomEvent",
        },
        "LogLevels": {"InfoLogLevel", "ErrorLogLevel", "WarningLogLevel"},
        "LogTypes": {"FileLogType", "ConsoleLogType"},
        "CustomEventHandler": {"notify"},
        "Event": {"add", "remove"},
        "ValueInput": {"createByString", "createByReal"},  # static
        "ObjectCollection": {"create"},  # static
        "Matrix3D": {"create"},  # static
        "Point3D": {"create", "x", "y", "z"},  # create static
        "Vector3D": {"create", "x", "y", "z"},  # create static
        "Point2D": {"create", "x", "y"},  # create static
        "BoundingBox3D": {"create", "minPoint", "maxPoint"},  # create static
        "MaterialLibraries": {"item", "itemByName", "count"},
        "MaterialLibrary": {"name", "appearances"},
        "Appearances": {"item", "itemByName", "count", "addByCopy"},
        "Appearance": {"name"},
        "DocumentTypes": {"FusionDesignDocumentType"},
        "ViewOrientations": {
            "FrontViewOrientation",
            "BackViewOrientation",
            "LeftViewOrientation",
            "RightViewOrientation",
            "TopViewOrientation",
            "BottomViewOrientation",
            "IsoTopRightViewOrientation",
            "IsoTopLeftViewOrientation",
            "IsoBottomRightViewOrientation",
            "IsoBottomLeftViewOrientation",
        },
        "CameraTypes": {
            "OrthographicCameraType",
            "PerspectiveCameraType",
            "PerspectiveWithOrthoFacesCameraType",
        },
        "SaveImageFileOptions": {
            "create",  # static
            "filename",
            "width",
            "height",
            "isBackgroundTransparent",
            "isAntiAliased",
        },
        "Documents": {"add", "open", "item", "itemByName", "count"},
        "Document": {
            "name",
            "isActive",
            "isModified",
            "isSaved",
            "dataFile",
            "product",
            "save",
            "saveAs",
            "close",
        },
        "DataFile": {"path", "version"},
        "UserInterface": {"messageBox", "activeWorkspace", "activeSelections"},
        "Workspace": {"name"},
        "Selections": {"count", "item"},
        "Selection": {"entity"},
        # Viewport.fit() exists in the real API but the tools drive fitting
        # through the camera (isFitView), so it is deliberately not pinned.
        "Viewport": {
            "camera",
            "width",
            "height",
            "refresh",
            "saveAsImageFile",
            "saveAsImageFileWithOptions",
        },
        "Camera": {
            "cameraType",
            "eye",
            "target",
            "upVector",
            "viewOrientation",
            "perspectiveAngle",
            "getExtents",
            "setExtents",
            "isFitView",
            "isSmoothTransition",
        },
    },
    "fusion": {
        "Design": {
            "cast",  # static, injected by the runtime wrapper
            "designType",
            "unitsManager",
            "fusionUnitsManager",
            "timeline",
            "rootComponent",
            "userParameters",
            "modelParameters",
            "exportManager",
            "appearances",
            "computeAll",
            "recomputedFeatureCount",
        },
        "DesignTypes": {"ParametricDesignType", "DirectDesignType"},
        "DistanceUnits": {
            "MillimeterDistanceUnits",
            "CentimeterDistanceUnits",
            "MeterDistanceUnits",
            "InchDistanceUnits",
        },
        "MeshRefinementSettings": {
            "MeshRefinementLow",
            "MeshRefinementMedium",
            "MeshRefinementHigh",
        },
        "ExportManager": {
            "createSTEPExportOptions",
            "createIGESExportOptions",
            "createFusionArchiveExportOptions",
            "createOBJExportOptions",
            "createSTLExportOptions",
            "createPDFExportOptions",
            "execute",
        },
        "UserParameters": {"add", "item", "itemByName", "count"},
        "ModelParameters": {"add", "item", "itemByName", "count"},
        "Parameter": {"name", "expression", "unit", "value", "isDriven"},
        "Component": {
            "name",
            "sketches",
            "features",
            "bodies",
            "occurrences",
            "xYConstructionPlane",
            "yZConstructionPlane",
            "zXConstructionPlane",
            "xConstructionAxis",
            "yConstructionAxis",
            "zConstructionAxis",
        },
        "ConstructionPlane": {"name"},
        "ConstructionAxis": {"name"},
        "Occurrences": {"item", "count", "addNewComponent"},
        "Occurrence": {"name", "component"},
        "Sketches": {"add", "item", "count"},
        "Sketch": {"name", "sketchCurves", "sketchPoints", "profiles", "isVisible"},
        "Profiles": {"item", "count"},
        "SketchCurves": {"sketchLines", "sketchCircles", "sketchArcs"},
        "SketchLines": {"addByTwoPoints"},
        "SketchCircles": {"addByCenterRadius"},
        "SketchArcs": {"addByCenterStartSweep"},
        "Features": {"item", "count"},
        "FilletFeatures": {"createInput", "add"},
        "ChamferFeatures": {"createInput2", "add"},
        "HoleFeatures": {"createSimpleInput", "add"},
        "RectangularPatternFeatures": {"createInput", "add"},
        "CircularPatternFeatures": {"createInput", "add"},
        "ExtrudeFeatures": {"createInput", "add"},
        "RevolveFeatures": {"createInput", "add"},
        "BaseFeatures": {"add"},
        "FilletFeatureInput": {"edgeSetInputs"},
        "FilletEdgeCollection": {"addConstantRadiusEdgeSet"},
        "ChamferFeatureInput": {"chamferEdgeSets"},
        "ChamferEdgeCollection": {"addEqualDistanceChamferEdgeSet"},
        "HoleFeatureInput": {
            "setPositionByPoint",
            "setDistanceExtent",
            "setAllExtent",
        },
        "RectangularPatternFeatureInput": {
            "quantityOne",
            "distanceOne",
            "quantityTwo",
            "distanceTwo",
            "directionTwoEntity",
            "isSymmetricInDirectionOne",
            "isSymmetricInDirectionTwo",
        },
        "CircularPatternFeatureInput": {
            "quantity",
            "totalAngle",
            "isSymmetric",
        },
        "ExtrudeFeatureInput": {
            "profile",
            "operation",
            "setOneSideExtent",
            "setSymmetricExtent",
        },
        "RevolveFeatureInput": {
            "profile",
            "axis",
            "operation",
            "setAngleExtent",
        },
        "BaseFeature": {"name", "startEdit", "finishEdit"},
        "ExtrudeFeature": {"name", "bodies"},
        "RevolveFeature": {"name", "bodies"},
        # Extent definitions are constructed by static create() calls.
        "DistanceExtentDefinition": {"create"},  # static
        "ThroughAllExtentDefinition": {"create"},  # static
        # Transient solid primitives, reached through TemporaryBRepManager.get().
        "TemporaryBRepManager": {"get"},  # static
        "TemporaryBRepBody": {"boundingBox", "volume"},
        "PatternDistanceType": {  # static enum
            "ExtentPatternDistanceType",
            "SpacingPatternDistanceType",
        },
        "ExtentDirections": {  # static enum
            "PositiveExtentDirection",
            "NegativeExtentDirection",
            "SymmetricExtentDirection",
        },
        "BRepBodies": {"add", "item", "count"},
        "BRepBody": {
            "name",
            "volume",
            "isSolid",
            "isVisible",
            "material",
            "boundingBox",
        },
        "BoundingBox": {"minPoint", "maxPoint"},
    },
}

# ── Live documentation cross-check ───────────────────────────────────────────

# Autodesk publishes reference pages as
#   https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/<ns>_<Class>.htm
# and member pages as <ns>_<Class>_<member>.htm.  The class page links every
# documented member, so asserting the member *name* appears on the class page
# is enough to prove the pin matches the real API.
LIVE_DOC_BASE = "https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files"

# Real members the runtime exposes but the published reference never lists.
# Each was verified against the live reference: no class-page entry and no
# member page of its own.  They are kept on the surface deliberately:
#
#   cast / recomputedFeatureCount
#       injected by the Python wrapper / read defensively through safe_get.
#   Event.add / Event.remove
#       Event is documented as a base class; the reference never lists the
#       subscription methods, though the runtime certainly provides them.
#   Documents.itemByName / ModelParameters.add
#       collection conveniences the fake provides; every tool reaches them
#       through a defensive getattr, so nothing depends on their existing.
#   Document.product / DataFile.path / DataFile.version
#       read through safe_get by the lifecycle/document tools.
#   Parameter.isDriven / Component.bodies / ExportManager.createPDFExportOptions
#       read through safe_get / getattr; the PDF creator is absent from this
#       API build and export_document reports that explicitly.
#   BoundingBox.*
#       the reference publishes BoundingBox3D; this is the fake's box helper.
UNDOCUMENTED_RUNTIME_MEMBERS = {
    ("fusion", "Design", "cast"),
    ("fusion", "Design", "recomputedFeatureCount"),
    ("core", "Event", "add"),
    ("core", "Event", "remove"),
    ("core", "Documents", "itemByName"),
    ("core", "Document", "product"),
    ("core", "DataFile", "path"),
    ("core", "DataFile", "version"),
    ("fusion", "ModelParameters", "add"),
    ("fusion", "Parameter", "isDriven"),
    ("fusion", "Component", "bodies"),
    ("fusion", "ExportManager", "createPDFExportOptions"),
    ("fusion", "BoundingBox", "minPoint"),
    ("fusion", "BoundingBox", "maxPoint"),
}

# Members documented on a *different* page than their owning class.  Used by
# the live-doc cross-check instead of the class page.
DOCUMENTED_ON: dict[tuple[str, str, str], str] = {
    # Design.modelParameters has no member page of its own; the reference
    # documents it as a member of Component.
    ("fusion", "Design", "modelParameters"): "fusion_Component",
}


def iter_pins():
    """Yield every pinned ``(namespace, class_name, member_name)``."""
    for namespace, classes in PINNED_SURFACE.items():
        for class_name, members in classes.items():
            for member in sorted(members):
                yield namespace, class_name, member


def live_doc_url(namespace: str, class_name: str, member: str | None = None) -> str:
    """URL of the reference page that documents ``class_name`` / ``member``."""
    override = DOCUMENTED_ON.get((namespace, class_name, member or ""))
    if override:
        return f"{LIVE_DOC_BASE}/{override}.htm"
    page = f"{namespace}_{class_name}"
    if member:
        page = f"{page}_{member}"
    return f"{LIVE_DOC_BASE}/{page}.htm"
