"""Fake ``Application``, user interface, viewport, camera, and selection set."""

from __future__ import annotations

import base64
import struct
import zlib

from . import values


def _solid_png(width: int, height: int, transparent: bool) -> bytes:
    """A minimal valid PNG of one solid color (viewport stand-in)."""
    width = max(1, int(width))
    height = max(1, int(height))
    if transparent:
        color_type, pixel = 6, b"\x12\x34\x56\xff"
    else:
        color_type, pixel = 2, b"\x12\x34\x56"
    raw = b"".join(b"\x00" + pixel * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class FakeWorkspace:
    def __init__(self, name="Design"):
        self.name = name


class FakeSelection:
    def __init__(self, entity):
        self.entity = entity


class FakeSelections:
    def __init__(self):
        self._items: list = []

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def add(self, entity):
        """Test helper: put an entity into the simulated selection set."""
        self._items.append(FakeSelection(entity))
        return self._items[-1]

    def clear(self):
        self._items.clear()


class FakeUserInterface:
    def __init__(self):
        self.activeWorkspace = FakeWorkspace()
        self.activeSelections = FakeSelections()
        self.messages: list[str] = []

    def messageBox(self, message):
        self.messages.append(str(message))


class FakeCamera:
    """Camera with the real wrapper's get/set extents split."""

    def __init__(self):
        self.cameraType = values.CameraTypes.PerspectiveCameraType
        self.eye = values.Point3D.create(0.0, 0.0, 10.0)
        self.target = values.Point3D.create(0.0, 0.0, 0.0)
        self.upVector = values.Vector3D.create(0.0, 1.0, 0.0)
        self.viewOrientation = values.ViewOrientations.IsoTopRightViewOrientation
        self.perspectiveAngle = 45.0
        self.isFitView = False
        self.isSmoothTransition = True
        self._extents = (10.0, 5.0)

    def getExtents(self):
        # Real wrapper: returns (ok, width, height) for the orthographic frustum.
        return True, self._extents[0], self._extents[1]

    def setExtents(self, width, height):
        self._extents = (float(width), float(height))
        return True


class FakeViewport:
    def __init__(self):
        self.camera = FakeCamera()
        self.width = 800
        self.height = 600
        self.refreshed = 0
        self.saved: list[tuple] = []

    def refresh(self):
        self.refreshed += 1
        return True

    def saveAsImageFile(self, filename):
        with open(filename, "wb") as handle:
            handle.write(_solid_png(self.width, self.height, False))
        self.saved.append((filename, self.width, self.height))
        return True

    def saveAsImageFileWithOptions(self, options):
        width = options.width or self.width
        height = options.height or self.height
        with open(options.filename, "wb") as handle:
            handle.write(_solid_png(width, height, bool(options.isBackgroundTransparent)))
        self.saved.append((options.filename, width, height))
        return True

    def capture_as_base64(self, options=None):
        return base64.b64encode(
            _solid_png(self.width, self.height, bool(getattr(options, "isBackgroundTransparent", False)))
        ).decode("ascii")


class FakeApplication:
    """The Fusion process singleton returned by ``adsk.core.Application.get``."""

    def __init__(self, documents, events: dict):
        self._documents = documents
        self._events = events
        self.userInterface = FakeUserInterface()
        self.activeViewport = FakeViewport()
        self.version = "2.0.0-fake"
        self.activeDocument = None
        self.logs: list[str] = []
        # Installed material/appearance libraries; the factory seeds the
        # standard one so apply_appearance has something honest to read.
        self.materialLibraries = None
        # Distance and angle measurement, reached as app.measureManager.
        from .features import FakeMeasureManager

        self.measureManager = FakeMeasureManager()
        # Documents become active the moment they are created or opened; the
        # collection drives that through this hook.
        documents._set_activate(self._activate)

    # -- documents --------------------------------------------------------

    @property
    def documents(self):
        return self._documents

    @property
    def activeProduct(self):
        document = self.activeDocument
        return None if document is None else document.product

    def _activate(self, document):
        for other in self._documents:
            other.isActive = other is document
        self.activeDocument = document

    # -- logging ----------------------------------------------------------

    def log(self, message, level=None):
        del level
        self.logs.append(str(message))

    # -- custom events (shared registry, mirrors _fusion_test_bootstrap) ----

    def registerCustomEvent(self, event_id):
        event = values.Event()
        self._events[event_id] = event
        return event

    def fireCustomEvent(self, event_id):
        event = self._events.get(event_id)
        if event is not None:
            event.notify_handlers()
        return True

    def unregisterCustomEvent(self, event_id):
        return self._events.pop(event_id, None) is not None


class ApplicationClass:
    """``adsk.core.Application`` replacement: ``get()`` returns the singleton."""

    _instance: FakeApplication | None = None

    @staticmethod
    def get():
        if ApplicationClass._instance is None:
            raise RuntimeError("Fake Application is not installed")
        return ApplicationClass._instance

    @staticmethod
    def _bind(instance: FakeApplication):
        ApplicationClass._instance = instance
