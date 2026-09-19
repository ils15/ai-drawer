"""Regression guard for the removed high-risk tool surface.

Wave 1 stripped the upstream tools that allowed an MCP client to execute
arbitrary work inside the Fusion process:

  * ``execute_python``      -- arbitrary Python execution (RCE)
  * ``call_autodesk_api``   -- generic dotted-path API caller
  * ``save_script`` / ``load_script`` / ``list_scripts`` / ``delete_script``
                               -- the user-script store

These tests exist because ``packages/addin`` is a git subtree of upstream and a
future ``git subtree pull`` can silently resurrect the modules and tool
definitions.  They fail loudly instead of letting a removed capability come
back through a merge.
"""

import importlib
import pathlib
import unittest

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)

from fusion_bridge import operations, tool_surface
from lib.mcp_server import MCPServer

# Tools that must never be served again.
BANNED_TOOLS = {
    "execute_python",
    "call_autodesk_api",
    "save_script",
    "load_script",
    "list_scripts",
    "delete_script",
}

# Modules deleted from the add-in package.
BANNED_MODULES = ("fusion_bridge.python_exec", "fusion_bridge.script_store")

# Shipped code directories scanned for banned literals. ``tests`` and the
# vendored Autodesk template are excluded: tests must be free to name the
# things they forbid, and third_party is byte-identical to upstream by design.
SHIPPED_SCAN_ROOTS = ("fusion_bridge", "lib", "commands")
SHIPPED_SCAN_FILES = ("settings.py", "config.py", "addon_runtime.py", "AutodeskFusionMCP.py")

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _shipped_python_files():
    for root in SHIPPED_SCAN_ROOTS:
        for path in (ROOT / root).rglob("*.py"):
            yield path
    for name in SHIPPED_SCAN_FILES:
        path = ROOT / name
        if path.exists():
            yield path


class RemovedToolTests(unittest.TestCase):
    """The removed tools must not be served, defined, or routable."""

    def test_banned_tools_absent_from_definitions(self):
        served = {t["name"] for t in tool_surface.TOOL_DEFINITIONS}
        self.assertEqual(served & BANNED_TOOLS, set())

    def test_banned_tools_absent_from_handler_registry(self):
        self.assertEqual(set(operations.TOOL_HANDLERS) & BANNED_TOOLS, set())

    def test_definitions_and_registry_agree(self):
        self.assertEqual(
            {t["name"] for t in tool_surface.TOOL_DEFINITIONS},
            set(operations.TOOL_HANDLERS),
        )

    def test_banned_tools_absent_from_assembled_server(self):
        """``runtime.create_server()`` is what actually answers tools/list."""
        from fusion_bridge import runtime

        server = runtime.create_server()
        try:
            served = {t["name"] for t in server.tools}
            self.assertEqual(served & BANNED_TOOLS, set())
            # The assembled server must not be the legacy single-tool fallback.
            self.assertIsInstance(server, MCPServer)
        finally:
            server.stop()

    def test_calling_a_banned_tool_is_rejected(self):
        """A banned name must route to an error result, not a handler."""
        for name in BANNED_TOOLS:
            with self.subTest(tool=name):
                self.assertNotIn(name, operations.TOOL_HANDLERS)


class RemovedModuleTests(unittest.TestCase):
    """The modules behind the removed tools must not exist."""

    def test_banned_modules_are_gone(self):
        for module_name in BANNED_MODULES:
            with self.subTest(module=module_name), self.assertRaises(ImportError):
                importlib.import_module(module_name)


class BannedLiteralScanTests(unittest.TestCase):
    """No banned tool name may appear anywhere in shipped add-in code.

    This is the guard that catches an upstream merge reintroducing a tool at
    the definition level even before the registry is rebuilt.
    """

    def test_no_banned_literals_in_shipped_code(self):
        offenders = []
        for path in _shipped_python_files():
            text = path.read_text(encoding="utf-8")
            for banned in BANNED_TOOLS:
                if banned in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {banned}")
        self.assertEqual(offenders, [], "banned tool literals found in shipped code")


if __name__ == "__main__":
    unittest.main()
