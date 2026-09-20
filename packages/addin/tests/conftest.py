"""Shared pytest configuration for the Fusion 360 add-in test suite.

Two things live here:

1.  Putting ``tests/`` on ``sys.path`` so the bootstrap, the ``fake_fusion``
    package, and sibling test helpers stay importable from subdirectories.

2.  The ``fusion`` fixture, which installs the behavioral fake around a single
    test and restores the exact ``adsk`` module state afterwards.  It is
    **not** autouse: tests that do not request it keep using the minimal mock
    the bootstrap installs, so the existing suite is untouched.
"""

import pathlib
import sys

import pytest

_TESTS_DIR = str(pathlib.Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

# Installs the minimal adsk mock and the synthetic parent package.  Idempotent.
import _fusion_test_bootstrap  # noqa: E402,F401


@pytest.fixture
def fusion():
    """Install a behavioral Fusion fake for exactly one test."""
    from fake_fusion import install, uninstall

    instance = install()
    try:
        yield instance
    finally:
        uninstall()


@pytest.fixture
def fusion_empty():
    """Like ``fusion`` but with no document open (the cold-start state)."""
    from fake_fusion import FakeFusion, install, uninstall

    instance = install(FakeFusion())
    try:
        yield instance
    finally:
        uninstall()


class _ResponseHelper:
    """Reads MCP response envelopes the way tool tests need to."""

    def text(self, response):
        return response["content"][0]["text"]

    def ok(self, response):
        assert not response.get("isError"), response
        import json

        return json.loads(self.text(response))

    def error(self, response):
        assert response.get("isError"), response
        return self.text(response)


@pytest.fixture
def mcp():
    """Helper for reading tool responses: ``mcp.ok(response)`` / ``mcp.error(...)``."""
    return _ResponseHelper()


@pytest.fixture
def call():
    """Invoke a shipped tool by name with plain arguments.

    Routes through ``operations.TOOL_HANDLERS`` -- the same registry the MCP
    server dispatches through -- so the JSON-RPC envelope unwrapping is
    exercised exactly as it is in production::

        response = call("new_document", name="Box")
    """

    def _call(tool_name, **arguments):
        from fusion_bridge import operations

        handler = operations.TOOL_HANDLERS[tool_name]
        return handler({"params": {"arguments": arguments}})

    return _call
