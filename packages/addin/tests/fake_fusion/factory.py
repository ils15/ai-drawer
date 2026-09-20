"""Factory that wires a complete fake Fusion runtime."""

from __future__ import annotations

from . import values
from .application import FakeApplication
from .design import FakeDesign
from .documents import FakeDocuments


class FakeFusion:
    """One simulated Fusion process: app, documents, and the active design."""

    def __init__(self):
        # Shared custom-event registry, mirroring the test bootstrap's
        # _MOCK_APP_EVENTS so dispatch.py's firing keeps working.
        self.events: dict = {}
        self.documents = FakeDocuments(self._create_design)
        self.app = FakeApplication(self.documents, self.events)

    def _create_design(self):
        return FakeDesign(), values.DocumentTypes.FusionDesignDocumentType

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


def make_fusion(with_document: bool = True, name: str = "Test Design") -> FakeFusion:
    """Build a fake Fusion.  By default one design document is already open."""
    fusion = FakeFusion()
    if with_document:
        fusion.new_document(name)
    return fusion
