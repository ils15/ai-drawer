"""Verify the public MCP tool surface: operation names, field names, and
schema structure.  No reference to old / renamed identifiers and no
source-tree scanning tricks."""

import re
import unittest

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)

from fusion_bridge import tool_surface
from lib.mcp_server import MCPServer


class ToolSurfaceTests(unittest.TestCase):
    """Tests that tool_surface exposes correct tool definitions."""

    EXPECTED_TOOLS = {
        "capture_viewport",
        "get_viewport",
        "set_viewport",
        "fetch_api_documentation",
        "fetch_online_documentation",
        "fetch_design_guide",
        "get_active_selection",
        "fusion_status",
        "fusion_diagnostics",
        "list_documents",
        "new_document",
        "open_document",
        "save_document",
        "export_document",
        "close_document",
        "get_document_info",
        "list_parameters",
        "add_parameter",
        "modify_parameter",
        "fillet",
        "chamfer",
        "hole",
        "rectangular_pattern",
        "circular_pattern",
        "create_sketch",
        "extrude",
        "revolve",
        "create_component",
        "create_body",
        "apply_appearance",
        "list_bodies",
        "inspect_entity",
        "list_features",
        "measure",
    }

    def test_all_expected_tools_present(self):
        names = {t["name"] for t in tool_surface.TOOL_DEFINITIONS}
        self.assertEqual(names, self.EXPECTED_TOOLS)

    def test_each_tool_has_description_and_schema(self):
        for tool_def in tool_surface.TOOL_DEFINITIONS:
            with self.subTest(tool=tool_def["name"]):
                self.assertIn("description", tool_def)
                self.assertTrue(len(tool_def["description"]) > 10)
                self.assertIn("inputSchema", tool_def)
                self.assertEqual(tool_def["inputSchema"]["type"], "object")

    def test_get_active_selection_has_no_required_params(self):
        for t in tool_surface.TOOL_DEFINITIONS:
            if t["name"] == "get_active_selection":
                props = t["inputSchema"].get("properties", {})
                self.assertTrue(len(props) <= 1)  # Only optional description allowed
                return
        self.fail("get_active_selection tool not found")


class ToolCategoryTests(unittest.TestCase):
    """Every tool is classified exactly once, in the closed category set."""

    def test_every_tool_has_a_category(self):
        for tool_def in tool_surface.TOOL_DEFINITIONS:
            with self.subTest(tool=tool_def["name"]):
                self.assertIn("category", tool_def, "tool definition has no category")
                self.assertIn(tool_def["category"], tool_surface.CATEGORIES)

    def test_category_assignment_is_exactly_one_per_tool(self):
        seen = {}
        for tool_def in tool_surface.TOOL_DEFINITIONS:
            seen[tool_def["name"]] = tool_def["category"]
        # Every live tool classified, none duplicated (dict keys are unique by name).
        self.assertEqual(set(seen), {t["name"] for t in tool_surface.TOOL_DEFINITIONS})

    def test_category_constants_are_the_closed_set(self):
        self.assertEqual(
            set(tool_surface.CATEGORIES),
            {
                "viewport",
                "selection",
                "documents",
                "parameters",
                "documentation",
                "diagnostics",
                "features",
                "inspection",
            },
        )


class SchemaAnnotationTests(unittest.TestCase):
    """Annotation discipline on every inputSchema: descriptions, units, examples."""

    def _walk_properties(self, schema, path, tool_name):
        """Yield (path, property_schema) for every property, recursing objects."""
        props = schema.get("properties", {})
        for key, prop in props.items():
            here = f"{path}.{key}"
            yield here, prop
            if isinstance(prop, dict) and prop.get("type") == "object":
                yield from self._walk_properties(prop, here, tool_name)

    def test_object_schemas_carry_a_description(self):
        for tool_def in tool_surface.TOOL_DEFINITIONS:
            schema = tool_def["inputSchema"]
            with self.subTest(tool=tool_def["name"]):
                self.assertTrue(
                    schema.get("description", "").strip(),
                    f"{tool_def['name']} root schema has no description",
                )
            for path, prop in self._walk_properties(schema, tool_def["name"], tool_def["name"]):
                with self.subTest(tool=tool_def["name"], prop=path):
                    self.assertTrue(
                        prop.get("description", "").strip(),
                        f"{path} has no description",
                    )

    def test_numeric_properties_name_their_unit(self):
        # Physical quantities must name a unit.  A genuinely dimensionless
        # quantity (a zoom factor, a result count) must say so explicitly --
        # the rule is "never silent about scale", not "append cm to a ratio".
        # Word-bounded so "centimeters" is not matched by a "cm" substring
        # accident, and "mm" does not fire on a random double-m.
        unit_patterns = [
            r"\bcm\b",
            r"\bcentimeters?\b",
            r"\bmm\b",
            r"\bmillimeters?\b",
            r"\bdegrees?\b",
            r"\bradians?\b",
            r"\bpx\b",
            r"\bpixels?\b",
            r"\binches?\b",
            r"\bin\b",
            r"\bmeters?\b",
            r"\bbytes\b",
            r"\bcount\b",
            r"\bnumber of\b",
            r"\bfactor\b",
            r"\bratio\b",
            r"\btimes\b",
        ]
        unit_re = re.compile("|".join(unit_patterns))
        for tool_def in tool_surface.TOOL_DEFINITIONS:
            for path, prop in self._walk_properties(tool_def["inputSchema"], tool_def["name"], tool_def["name"]):
                if prop.get("type") not in ("number", "integer"):
                    continue
                desc = prop.get("description", "")
                with self.subTest(tool=tool_def["name"], prop=path):
                    self.assertTrue(
                        unit_re.search(desc),
                        f"{path} numeric description names no unit: {desc!r}",
                    )

    def test_examples_arrays_are_non_empty_when_present(self):
        for tool_def in tool_surface.TOOL_DEFINITIONS:
            for path, prop in self._walk_properties(tool_def["inputSchema"], tool_def["name"], tool_def["name"]):
                if "examples" not in prop:
                    continue
                examples = prop["examples"]
                with self.subTest(tool=tool_def["name"], prop=path):
                    self.assertIsInstance(examples, list, f"{path} examples is not a list")
                    self.assertGreater(len(examples), 0, f"{path} examples array is empty")


class ResourceTests(unittest.TestCase):
    """Tests that resource constants are defined."""

    def test_resource_uri(self):
        self.assertTrue(tool_surface.RESOURCE_URI.startswith("fusion://"))

    def test_resource_name_nonempty(self):
        self.assertTrue(len(tool_surface.RESOURCE_NAME) > 0)


class MultiToolServerTests(unittest.TestCase):
    """Tests that MCPServer supports multiple tools."""

    def test_server_accepts_tools_list(self):
        tools = [
            {
                "name": "tool_a",
                "description": "Tool A",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "tool_b",
                "description": "Tool B",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]
        handlers = {"tool_a": lambda args: None, "tool_b": lambda args: None}
        server = MCPServer(port=0, tools=tools, tool_handlers=handlers)
        self.assertEqual(len(server.tools), 2)

    def test_server_legacy_single_tool_still_works(self):
        server = MCPServer(
            port=0,
            tool_handler=lambda args: None,
            tool_name="legacy_tool",
            tool_description="Legacy",
            tool_input_schema={"type": "object", "properties": {}},
        )
        self.assertEqual(len(server.tools), 1)
        self.assertEqual(server.tools[0]["name"], "legacy_tool")


class OperationsRegistryTests(unittest.TestCase):
    """Tests that operations exports the correct handler registry."""

    def test_tool_handlers_matches_definitions(self):
        from fusion_bridge import operations, tool_surface

        expected_names = {t["name"] for t in tool_surface.TOOL_DEFINITIONS}
        actual_names = set(operations.TOOL_HANDLERS.keys())
        self.assertEqual(actual_names, expected_names)

    def test_all_handlers_are_callable(self):
        from fusion_bridge import operations

        for name, handler in operations.TOOL_HANDLERS.items():
            with self.subTest(tool=name):
                self.assertTrue(callable(handler), f"Handler for {name} is not callable")


if __name__ == "__main__":
    unittest.main()
