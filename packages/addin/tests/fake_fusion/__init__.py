"""Behavioral fake of the Autodesk Fusion (``adsk``) runtime for offline tests.

The fake implements exactly the pinned real-API surface (see
:mod:`.surface`) and computes real geometry: profile closure by endpoint
chaining, parameter values via an expression engine, and bodies with bounding
boxes that move when a parameter does.  It is installed by *in-place attribute
mutation* of the existing ``adsk`` modules (see :mod:`.bootstrap`), never by
module replacement, so it survives any import order.

Install it with the ``fusion`` pytest fixture in ``tests/conftest.py`` -- it is
deliberately not installed globally, so it cannot affect tests that do not ask
for it.
"""

from .bootstrap import install, installed, is_installed, uninstall
from .factory import FakeFusion, make_fusion
from .surface import PINNED_SURFACE, iter_pins, live_doc_url

__all__ = [
    "FakeFusion",
    "PINNED_SURFACE",
    "install",
    "installed",
    "is_installed",
    "iter_pins",
    "live_doc_url",
    "make_fusion",
    "uninstall",
]
