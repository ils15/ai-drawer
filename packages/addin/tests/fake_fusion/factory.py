"""Factory that wires a complete fake Fusion runtime."""

from __future__ import annotations

from . import values
from .application import FakeApplication
from .design import FakeDesign
from .documents import FakeDocuments
from .failures import FailureInjector


class FakeFusion:
    """One simulated Fusion process: app, documents, and the active design."""

    def __init__(self):
        # Shared custom-event registry, mirroring the test bootstrap's
        # _MOCK_APP_EVENTS so dispatch.py's firing keeps working.
        self.events: dict = {}
        # One-shot failure injection (see .failures).  Opt-in per test: a kind
        # only fires after fail_next() queues it, and only once.
        self.failures = FailureInjector()
        self.documents = FakeDocuments(self._create_design, self.failures)
        self.app = FakeApplication(self.documents, self.events)
        # The installed libraries are part of the process, not the document.
        from .features import default_material_libraries

        self.app.materialLibraries = default_material_libraries()

    def _create_design(self):
        return (
            FakeDesign(failures=self.failures),
            values.DocumentTypes.FusionDesignDocumentType,
        )

    # -- failure injection --------------------------------------------------

    def fail_next(self, kind):
        """Queue a simulated Fusion failure for the next matching call.

        See ``fake_fusion.failures`` for the kind list.  The injection fires
        once and clears itself, so a test asserts exactly one error branch.
        """
        self.failures.fail_next(kind)

    # -- active state -----------------------------------------------------

    @property
    def document(self):
        return self.app.activeDocument

    @property
    def design(self):
        product = self.app.activeProduct
        return None if product is None else FakeDesign.cast(product)

    @property
    def root(self):
        design = self.design
        return None if design is None else design.rootComponent

    @property
    def timeline(self):
        design = self.design
        return None if design is None else design.timeline

    @property
    def user_parameters(self):
        design = self.design
        return None if design is None else design.userParameters

    @property
    def viewport(self):
        return self.app.activeViewport

    # -- test helpers -----------------------------------------------------

    def new_document(self, name="Untitled", design_type="parametric"):
        """Open and activate a fresh document, as the new_document tool does."""
        document = self.documents.add(values.DocumentTypes.FusionDesignDocumentType)
        document.name = name
        self.app._activate(document)
        if design_type == "direct":
            design = self.design
            if design is not None:
                design.designType = values.DesignTypes.DirectDesignType
        return document

    def open_document(self, path):
        """Open an existing file, as the open_document tool does."""
        document = self.documents.open(path)
        if document is not None:
            self.app._activate(document)
        return document

    def add_parameter(self, name, expression, unit="mm"):
        """Add a user parameter, as the add_parameter tool does."""
        value_input = values.ValueInput.createByString(expression)
        return self.user_parameters.add(name, value_input, unit, "")

    # -- geometry helpers --------------------------------------------------

    def add_edge(self, name, length, token=None):
        """Create a BRepEdge and select it, as a user clicking an edge would.

        Feature tools address geometry by *stored selection handle*, so the
        honest way to give a test an edge to fillet is to put one in the
        selection set.  ``get_active_selection`` then stores it as
        ``$selection_0``, which the fillet or chamfer tool resolves back to
        this very object.
        """
        from .features import FakeBRepEdge

        edge = FakeBRepEdge(name, length, entity_token=token)
        self.app.userInterface.activeSelections.add(edge)
        return edge

    def add_face(self, name, area=1.0, token=None, is_planar=True):
        """Create a BRepFace and select it (the hole tool starts on one).

        ``is_planar=False`` gives a curved face, which a simple hole cannot be
        positioned on -- the hole tool reports that as ``invalid_value``.
        """
        from .features import FakeBRepFace

        face = FakeBRepFace(name, area=area, entity_token=token, is_planar=is_planar)
        self.app.userInterface.activeSelections.add(face)
        return face

    def add_body(self, name="Body1", shape="box", length=2.0, width=2.0, height=2.0, radius=1.0, select=True):
        """Create a primitive body in the root component, and select it by default.

        The geometry is real: a box or cylinder or sphere built by the transient
        BRep manager, so its volume, area, and extent are derived from the
        dimensions and an inspection or measurement sees the same numbers.
        Adding a transient body to a design makes it a real ``BRepBody`` (with an
        entity token, area, and face/edge collections), so the fake wraps it the
        same way -- an inspection that reads ``objectType`` sees BRepBody, not
        the transient kind the primitive was built as.
        """
        from .features import FakeBRepBody, FakeTemporaryBRepManager

        manager = FakeTemporaryBRepManager.get()
        if shape == "box":
            temporary = manager.createBox(
                values.BoundingBox3D.create(values.Point3D.create(), values.Point3D.create(length, width, height))
            )
        elif shape == "cylinder":
            temporary = manager.createCylinderOrCone(
                values.Point3D.create(), values.Point3D.create(0.0, 0.0, height), radius, radius
            )
        elif shape == "sphere":
            temporary = manager.createSphere(values.Point3D.create(), radius)
        else:  # pragma: no cover - guarded by the shape enum
            raise ValueError(f"unknown shape: {shape}")
        body = self.root.bodies.add(FakeBRepBody(name, temporary_body=temporary))
        if select:
            self.app.userInterface.activeSelections.add(body)
        return body

    def add_timeline_node(self, name, kind, health=None, message="", is_suppressed=False):
        """Append a timeline node that is not a feature (a sketch, joint, or PMI).

        The timeline holds these alongside features, and list_features reports
        every node, so a test needs one to exercise a mixed timeline.
        """
        from .features import FakeTimelineObject

        node = FakeTimelineObject(name, kind, health=health, message=message, is_suppressed=is_suppressed)
        self.timeline._append_feature(node)
        return node


def make_fusion(with_document: bool = True, name: str = "Test Design") -> FakeFusion:
    """Build a fake Fusion.  By default one design document is already open."""
    fusion = FakeFusion()
    if with_document:
        fusion.new_document(name)
    return fusion
