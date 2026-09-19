"""Tests for the MCP tool routing wrappers in :mod:`fusion_bridge.operations`.

The registry maps every tool definition to a small closure that unpacks a
JSON-RPC ``call_data`` envelope before handing the arguments to the real
handler.  Those closures are the whole point of the module, so they are
exercised both directly and through the shipped registry.
"""

import unittest

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)

from fusion_bridge import operations


class WrapperHelperTests(unittest.TestCase):
    """``_wrap`` / ``_wrap_doc`` must unwrap the JSON-RPC envelope faithfully."""

    def test_wrap_extracts_arguments_from_call_data(self):
        wrapped = operations._wrap(lambda arguments: arguments)
        self.assertEqual(wrapped({"params": {"arguments": {"a": 1}}}), {"a": 1})

    def test_wrap_defaults_to_empty_arguments(self):
        wrapped = operations._wrap(lambda arguments: arguments)
        self.assertEqual(wrapped({}), {})

    def test_wrap_ignores_envelope_noise(self):
        wrapped = operations._wrap(lambda arguments: arguments)
        envelope = {"jsonrpc": "2.0", "id": 7, "params": {"name": "x", "arguments": {"kept": True}}}
        self.assertEqual(wrapped(envelope), {"kept": True})

    def test_wrap_doc_receives_arguments_and_log(self):
        calls = []

        def handler(arguments, log_fn):
            calls.append((arguments, log_fn))
            return "ok"

        wrapped = operations._wrap_doc(handler)
        self.assertEqual(wrapped({"params": {"arguments": {"k": "v"}}}), "ok")
        # The log function is injected by the registry, not by the caller.
        self.assertEqual(calls, [({"k": "v"}, operations.log)])

    def test_wrap_doc_defaults_to_empty_arguments(self):
        wrapped = operations._wrap_doc(lambda arguments, log_fn: arguments)
        self.assertEqual(wrapped({}), {})


class RegistryEnvelopeTests(unittest.TestCase):
    """Every shipped handler must accept a real call_data envelope."""

    def test_handlers_return_mcp_response_for_empty_arguments(self):
        for name, handler in operations.TOOL_HANDLERS.items():
            with self.subTest(tool=name):
                self.assertTrue(callable(handler), f"handler for {name} is not callable")
                response = handler({"params": {"arguments": {}}})
                self.assertIsInstance(response, dict, f"{name} did not return a dict")
                self.assertIn("isError", response, f"{name} returned no isError flag")

    def test_registry_covers_every_defined_tool(self):
        from fusion_bridge import tool_surface

        self.assertEqual(
            set(operations.TOOL_HANDLERS),
            {t["name"] for t in tool_surface.TOOL_DEFINITIONS},
        )


if __name__ == "__main__":
    unittest.main()
