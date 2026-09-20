"""Fake document collection, documents, and saved-file records."""

from __future__ import annotations

import os
from collections.abc import Callable

from . import values
from .failures import FailureInjector


class FakeDataFile:
    """The ``document.dataFile`` record: where the document is saved on disk."""

    def __init__(self, path, version=1):
        self.path = path
        self.version = version


class FakeDocument:
    """One open document.  Created through ``FakeDocuments.add`` / ``.open``."""

    def __init__(self, name, product, doc_type):
        self.name = name
        self.product = product
        self.documentType = doc_type
        self.isActive = False
        self.isModified = False
        self.isSaved = False
        self.dataFile: FakeDataFile | None = None
        self.closed = False

    # -- mutations --------------------------------------------------------

    def save(self):
        if self.dataFile is None:
            # The tools gate on isSaved before reaching here; mirror the real
            # API's refusal anyway so the fake cannot agree with a bad call.
            return False
        self.isModified = False
        return True

    def saveAs(self, name, folder, technology="", comment=""):
        del technology, comment
        folder = folder or "."
        filename = name or "Untitled"
        if not filename.lower().endswith((".f3d", ".f3z")):
            filename = f"{filename}.f3d"
        self.dataFile = FakeDataFile(os.path.join(folder, filename))
        self.name = filename
        self.isSaved = True
        self.isModified = False
        return True

    def close(self, save_changes=False):
        if save_changes and self.dataFile is not None:
            self.isModified = False
        self.closed = True
        return True


class FakeDocuments:
    """``app.documents``: add/open by path, look up by index or name."""

    def __init__(self, create_design, failures=None):
        # create_design() -> (product, doc_type) for a brand-new design.
        self._create_design = create_design
        # Failure injection (see .failures); a standalone collection gets its
        # own injector, which simply never has anything queued.
        self._failures = failures if failures is not None else FailureInjector()
        self._items: list[FakeDocument] = []
        # Real Fusion activates a document as soon as it is created or opened;
        # the Application registers its hook so the tools see that happen.
        self._activate: Callable[[FakeDocument], None] | None = None

    def _set_activate(self, activate):
        """Wire the activation hook set by ``FakeApplication``."""
        self._activate = activate

    def _activate_document(self, document):
        if document is not None and self._activate is not None:
            self._activate(document)
        return document

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def itemByName(self, name):
        for document in self._items:
            if document.name == name:
                return document
        return None

    def add(self, doc_type):
        product, kind = self._create_design()
        document = FakeDocument("Untitled", product, doc_type)
        self._items.append(document)
        # A newly created document becomes active, as in real Fusion.
        return self._activate_document(document)

    def open(self, path):
        # Simulated Fusion refusal, queued by fail_next("open_returns_none").
        # Fires before the path check so a test can inject it even with a
        # valid on-disk file (the fake otherwise cannot fail that way).
        if self._failures.fire("open_returns_none"):
            return None
        # Real Fusion refuses a path it cannot read; the fake mirrors that so
        # open_document's "could not open" branch is reachable in tests.
        if not path or not os.path.isfile(path):
            return None
        product, kind = self._create_design()
        document = FakeDocument(os.path.basename(path), product, kind)
        document.dataFile = FakeDataFile(path)
        document.isSaved = True
        self._items.append(document)
        # Opening a document makes it active, as in real Fusion.
        return self._activate_document(document)

    def _remove(self, document):
        if document in self._items:
            self._items.remove(document)

    def __iter__(self):
        return iter(self._items)


def create_document_types():
    return values.DocumentTypes
