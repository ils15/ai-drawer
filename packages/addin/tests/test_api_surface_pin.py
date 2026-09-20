"""The anti-drift contract between three things that must agree:

1.  what the shipped tools actually *call* (``adsk.core.X``, ``adsk.fusion.Y``),
2.  what the behavioral fake *implements*, and
3.  what Autodesk's published reference *documents*.

This is the failure mode that shipped two broken community servers: a mock that
implements more (or less) than the real API silently agrees with a wrong
assumption, so every test written against it passes while the real product
fails.  The fake therefore implements only the pinned surface in
``fake_fusion.surface``, and this file holds all three sides to that pin.

Layer (a) -- offline, always runs:

* every ``adsk.<ns>.<Class>.<member>`` literal the tools reach is extracted from
  the source and must be pinned, and
* every pinned member must exist on the installed fake.

A tool reaching something the fake lacks fails here, in a focused test, instead
of surfacing as a mysterious failure in a feature test later.

Layer (b) -- network-gated (``@pytest.mark.network``, skipped by default): for
every pinned class the live Autodesk reference page is fetched and the pinned
members are checked against the documented ones.
``UNDOCUMENTED_RUNTIME_MEMBERS`` holds the verified exceptions -- wrapper-
injected members, defensively-read conveniences, and members the reference
publishes under a different class.  Anything else that drifts fails.
"""

import ast
import pathlib
import re
import urllib.request

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)
import pytest
from fake_fusion import PINNED_SURFACE, install, iter_pins, uninstall
from fake_fusion.surface import DOCUMENTED_ON, UNDOCUMENTED_RUNTIME_MEMBERS, live_doc_url

_SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "fusion_bridge"
_LIVE_DOC_BASE = "https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files"
_API_CELL = re.compile(r'<td class="api-list">\s*<a [^>]*>([A-Za-z0-9_]+)</a>')
_WORD = r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])"


# ── Extraction: what the tools actually call ────────────────────────────────


def _attribute_chain(node):
    """Collapse an ``a.b.c.d`` Attribute node into its name list, else None."""
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    names.append(node.id)
    return list(reversed(names))


def _extract_adsk_calls():
    """Return every ``adsk.<ns>.<Class>.<member>`` literal the tools reach.

    The AST is walked rather than regexing the text so that fragments inside
    comments and docstrings cannot sneak in.
    """
    calls: set[tuple[str, str, str]] = set()
    for source in sorted(_SOURCE_ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(source.read_text())):
            chain = _attribute_chain(node)
            if chain is None or len(chain) < 4 or chain[0] != "adsk":
                continue
            namespace, class_name, member = chain[1], chain[2], chain[3]
            if namespace in ("core", "fusion") and class_name[:1].isupper():
                calls.add((namespace, class_name, member))
    return calls


# ── The object graph the tools hold ─────────────────────────────────────────


def _sample_graph(fusion):
    """Map every pinned class to a live instance reachable from the fake.

    Cold-start objects (sketch, profile, parameter, body) are created so that
    the instance members of the classes behind them can be probed too.
    """
    import fake_fusion.values as values
    from fake_fusion.documents import FakeDataFile

    app = fusion.app
    design = fusion.design
    root = design.rootComponent
    sketch = root.sketches.add()
    # ``make_fusion`` creates an unsaved document, while the live API always
    # exposes a DataFile object for the saved-document members pinned below.
    # Attach the real fake record rather than replacing it with a test double.
    fusion.document.dataFile = FakeDataFile("/tmp/pin-check.f3d", version=1)
    fusion.document.isSaved = True

    graph: dict[tuple[str, str], object] = {
        ("core", "Application"): app,
        ("core", "Documents"): app.documents,
        ("core", "Document"): fusion.document,
        ("core", "DataFile"): fusion.document.dataFile,
        ("core", "UserInterface"): app.userInterface,
        ("core", "Workspace"): app.userInterface.activeWorkspace,
        ("core", "Selections"): app.userInterface.activeSelections,
        ("core", "Viewport"): app.activeViewport,
        ("core", "Camera"): app.activeViewport.camera,
        ("core", "CustomEventHandler"): values.CustomEventHandler,
        ("core", "Event"): app.registerCustomEvent("pin_check"),
        ("core", "Point3D"): values.Point3D.create(),
        ("core", "Vector3D"): values.Vector3D.create(),
        ("core", "Point2D"): values.Point2D.create(),
        ("core", "SaveImageFileOptions"): values.SaveImageFileOptions.create("pin.png"),
        ("fusion", "Design"): design,
        ("fusion", "UserParameters"): design.userParameters,
        ("fusion", "ModelParameters"): design.modelParameters,
        ("fusion", "ExportManager"): design.exportManager,
        ("fusion", "Component"): root,
        ("fusion", "Sketches"): root.sketches,
        ("fusion", "Sketch"): sketch,
        ("fusion", "SketchCurves"): sketch.sketchCurves,
        ("fusion", "SketchPoints"): sketch.sketchPoints,
        ("fusion", "Profiles"): sketch.profiles,
        ("fusion", "Features"): root.features,
        ("fusion", "BRepBodies"): root.bodies,
    }

    parameter = design.userParameters.add("pin_check", values.ValueInput.createByString("10 mm"), "mm", "")
    graph[("fusion", "Parameter")] = parameter

    sketch.add_line(0, 0, 1, 0)
    sketch.add_line(1, 0, 1, 1)
    sketch.add_line(1, 1, 0, 1)
    sketch.add_line(0, 1, 0, 0)
    profile = sketch.profiles.item(0)
    feature = root.features.add_extrude(profile, 1.0, "PinCheck")
    graph[("fusion", "BRepBody")] = feature.body
    graph[("fusion", "BoundingBox")] = profile.boundingBox
    graph[("core", "Selection")] = app.userInterface.activeSelections.add(
        sketch.sketchPoints.add(values.Point3D.create())
    )

    # Feature-tool inputs are cold-start objects too: the handlers reach them
    # through createInput(), so the instance attributes the pin lists
    # (edgeSetInputs, quantityOne, totalAngle, ...) need an instance to probe.
    from fake_fusion.features import FakeBRepEdge

    direction = FakeBRepEdge("PinDirection", 2.0)
    fillet_input = root.features.filletFeatures.createInput()
    chamfer_input = root.features.chamferFeatures.createInput2()
    hole_input = root.features.holeFeatures.createSimpleInput(values.ValueInput.createByReal(0.5))
    rect_input = root.features.rectangularPatternFeatures.createInput(
        [feature.body],
        direction,
        values.ValueInput.createByReal(2),
        values.ValueInput.createByReal(1.0),
        values.PatternDistanceType.SpacingPatternDistanceType,
    )
    circular_input = root.features.circularPatternFeatures.createInput([feature.body], direction)
    graph[("fusion", "FilletFeatureInput")] = fillet_input
    graph[("fusion", "FilletEdgeCollection")] = fillet_input.edgeSetInputs
    graph[("fusion", "ChamferFeatureInput")] = chamfer_input
    graph[("fusion", "ChamferEdgeCollection")] = chamfer_input.chamferEdgeSets
    graph[("fusion", "HoleFeatureInput")] = hole_input
    graph[("fusion", "RectangularPatternFeatureInput")] = rect_input
    graph[("fusion", "CircularPatternFeatureInput")] = circular_input

    # The sketch/extrude/revolve/component/body/appearance tools reach their
    # inputs through createInput() too, so the pinned instance members
    # (setOneSideExtent, setAngleExtent, appearances, component, ...) need
    # live objects to probe.
    import adsk.core
    import adsk.fusion

    extrude_input = root.features.extrudeFeatures.createInput(
        profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    extrude_input.setOneSideExtent(
        adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByReal(1.0)),
        adsk.fusion.ExtentDirections.PositiveExtentDirection,
    )
    extrude_feature = root.features.extrudeFeatures.add(extrude_input)
    revolve_input = root.features.revolveFeatures.createInput(
        profile, root.xConstructionAxis, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    revolve_input.setAngleExtent(False, adsk.core.ValueInput.createByReal(90.0))
    revolve_feature = root.features.revolveFeatures.add(revolve_input)
    graph[("fusion", "ExtrudeFeatureInput")] = extrude_input
    graph[("fusion", "RevolveFeatureInput")] = revolve_input
    graph[("fusion", "ExtrudeFeature")] = extrude_feature
    graph[("fusion", "RevolveFeature")] = revolve_feature

    base_feature = root.features.baseFeatures.add()
    graph[("fusion", "BaseFeature")] = base_feature

    from fake_fusion.features import FakeTemporaryBRepManager

    temporary_body = FakeTemporaryBRepManager.get().createBox(
        adsk.core.BoundingBox3D.create(adsk.core.Point3D.create(), adsk.core.Point3D.create(1.0, 1.0, 1.0))
    )
    graph[("fusion", "TemporaryBRepBody")] = temporary_body

    occurrence = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    graph[("fusion", "Occurrences")] = root.occurrences
    graph[("fusion", "Occurrence")] = occurrence
    graph[("fusion", "ConstructionPlane")] = root.xYConstructionPlane
    graph[("fusion", "ConstructionAxis")] = root.xConstructionAxis

    # Material libraries are reached through the application; the appearance
    # tool copies an appearance out of one into the design.
    graph[("core", "MaterialLibraries")] = app.materialLibraries
    library = app.materialLibraries.itemByName("Fusion 360 Material Library")
    graph[("core", "MaterialLibrary")] = library
    graph[("core", "Appearances")] = library.appearances
    graph[("core", "Appearance")] = library.appearances.itemByName("Steel")
    graph[("core", "BoundingBox3D")] = adsk.core.BoundingBox3D.create(
        adsk.core.Point3D.create(), adsk.core.Point3D.create(1.0, 1.0, 1.0)
    )

    return graph


# ── Layer (a): offline, always runs ─────────────────────────────────────────


@pytest.fixture(scope="module")
def adsk_calls():
    return _extract_adsk_calls()


@pytest.fixture(scope="module")
def installed_fake():
    """One fake install for the whole module; restored afterwards."""
    fusion = install()
    yield fusion
    uninstall()


def test_every_adsk_call_is_pinned(adsk_calls):
    """No tool reaches an ``adsk`` member the pin registry does not list."""
    unpinned = sorted(set(adsk_calls) - set(iter_pins()))
    assert not unpinned, f"tools call adsk members the fake does not pin: {unpinned}"


def test_every_pinned_member_exists_on_the_fake(installed_fake):
    """Each pinned member is reachable on the fake, statically or on an instance.

    Methods live on the class, attributes on instances; a member passes if it is
    found in either place.
    """
    import adsk.core
    import adsk.fusion

    modules = {"core": adsk.core, "fusion": adsk.fusion}
    graph = _sample_graph(installed_fake)

    missing = []
    for namespace, class_name, member in sorted(iter_pins()):
        module = modules[namespace]
        if hasattr(module, class_name) and hasattr(getattr(module, class_name), member):
            continue  # static, enum member, or method on the class
        instance = graph.get((namespace, class_name))
        if instance is not None and hasattr(instance, member):
            continue
        missing.append(f"{namespace}.{class_name}.{member}")
    assert not missing, f"pinned members the fake does not implement: {missing}"


# ── Layer (b): live documentation cross-check ───────────────────────────────


def _fetch(url):
    """Return the page body, or None when it cannot be reached."""
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return response.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - any fetch failure means "cannot verify"
        return None


def _documented_members(namespace, class_name):
    """Fetch a class page and return its documented member names, or None."""
    body = _fetch(live_doc_url(namespace, class_name))
    if body is None:
        return None
    return set(_API_CELL.findall(body))


@pytest.mark.network
@pytest.mark.parametrize(
    "namespace, class_name",
    [(ns, cls) for ns, classes in PINNED_SURFACE.items() for cls in classes],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_pinned_members_are_documented_by_autodesk(namespace, class_name):
    """Every pinned member appears in the live reference for its class.

    Skipped unless run with ``-m network``.  Fails on drift: a member the
    reference no longer lists, or a pin that named a member that never existed.
    """
    documented = _documented_members(namespace, class_name)
    if documented is None:
        pytest.skip(f"could not fetch {namespace}_{class_name}.htm")

    undocumentable = []
    for member in sorted(PINNED_SURFACE[namespace][class_name]):
        if (namespace, class_name, member) in UNDOCUMENTED_RUNTIME_MEMBERS:
            continue
        if _is_documented(namespace, class_name, member, documented):
            continue
        undocumentable.append(member)

    assert not undocumentable, f"{namespace}.{class_name}: pinned but not documented: {undocumentable}"


def _is_documented(namespace, class_name, member, documented):
    """True when the reference documents *member* for the class.

    Three kinds of evidence count, in order of reliability: the member's entry
    in the class's API table, an entry on another class's page (DOCUMENTED_ON),
    and -- for classes whose members the table does not enumerate at all -- a
    name mention on the class page.
    """
    if member in documented:
        return True

    override = DOCUMENTED_ON.get((namespace, class_name, member))
    if override:
        override_body = _fetch(f"{_LIVE_DOC_BASE}/{override}.htm")
        if override_body is not None and member in set(_API_CELL.findall(override_body)):
            return True

    # Enum-style classes list their members as page text, not as a table.
    if not documented:
        class_body = _fetch(live_doc_url(namespace, class_name))
        if class_body is not None and re.search(_WORD.format(re.escape(member)), class_body):
            return True

    return False
