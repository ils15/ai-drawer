"""Tests for the canonical error taxonomy and the structured MCP error envelope.

Covers the three properties the Phase-2 reliability work promised a client:

* the taxonomy in ``ERROR_KINDS`` is closed and self-consistent -- every kind
  carries a default message and a non-empty actionable hint, so a call site
  that only knows the kind still returns something useful;
* an unrecognized kind degrades to ``internal`` instead of raising, because a
  bad error name must never become a second failure while reporting one;
* no error response ever carries a stack trace, an exception repr, or the
  string ``format_exc`` -- the detail stays in the add-in log, never in the
  content an LLM client can read.
"""

import json
import pathlib
import unittest

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)

from fusion_bridge import errors

_PACKAGE_DIR = pathlib.Path(errors.__file__).resolve().parent

# Markers that must never reach a client.  ``Traceback`` is the CPython banner;
# ``format_exc`` would mean an ``except`` block stringified a live stack.
_LEAK_MARKERS = ("Traceback", "format_exc")


class TaxonomyTests(unittest.TestCase):
    """``ERROR_KINDS`` plus its default tables must be closed and complete."""

    def test_kinds_are_unique_nonempty_strings(self):
        self.assertEqual(len(errors.ERROR_KINDS), len(set(errors.ERROR_KINDS)))
        for kind in errors.ERROR_KINDS:
            self.assertIsInstance(kind, str)
            self.assertTrue(kind.strip(), f"empty kind: {kind!r}")

    def test_every_kind_has_a_nonempty_default_message(self):
        for kind in errors.ERROR_KINDS:
            self.assertIn(kind, errors.DEFAULT_MESSAGES, f"no message for {kind}")
            self.assertTrue(errors.DEFAULT_MESSAGES[kind].strip())

    def test_every_kind_has_a_nonempty_default_hint(self):
        for kind in errors.ERROR_KINDS:
            self.assertIn(kind, errors.DEFAULT_HINTS, f"no hint for {kind}")
            hint = errors.DEFAULT_HINTS[kind]
            self.assertTrue(hint.strip(), f"empty hint for {kind}")

    def test_default_tables_add_no_stray_kinds(self):
        self.assertEqual(set(errors.DEFAULT_MESSAGES), set(errors.ERROR_KINDS))
        self.assertEqual(set(errors.DEFAULT_HINTS), set(errors.ERROR_KINDS))

    def test_internal_is_the_last_resort_kind(self):
        # The catch-all must exist so degradation always lands somewhere.
        self.assertIn("internal", errors.ERROR_KINDS)


class EnvelopeTests(unittest.TestCase):
    """``structured_error`` / ``internal_error`` response shape and fallbacks."""

    def test_envelope_shape_matches_a_success(self):
        response = errors.structured_error("not_found")
        self.assertTrue(response["isError"])
        content = response["content"]
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["type"], "text")
        # The text is JSON a client can parse, not prose.
        payload = json.loads(content[0]["text"])
        self.assertEqual(set(payload), {"error_kind", "message", "hint"})

    def test_explicit_message_and_hint_win_over_defaults(self):
        response = errors.structured_error("invalid_value", "nope", "fix it")
        payload = json.loads(response["content"][0]["text"])
        self.assertEqual(payload["error_kind"], "invalid_value")
        self.assertEqual(payload["message"], "nope")
        self.assertEqual(payload["hint"], "fix it")

    def test_empty_message_and_hint_fall_back_to_defaults(self):
        # Falsy (not just missing) arguments must still yield useful text.
        response = errors.structured_error("io_failure", "", "")
        payload = json.loads(response["content"][0]["text"])
        self.assertEqual(payload["message"], errors.DEFAULT_MESSAGES["io_failure"])
        self.assertEqual(payload["hint"], errors.DEFAULT_HINTS["io_failure"])

    def test_unknown_kind_degrades_to_internal(self):
        for bogus in ("bogus_kind", "", None, "NOT_FOUND", "internal "):
            with self.subTest(kind=bogus):
                payload = json.loads(errors.structured_error(bogus)["content"][0]["text"])
                self.assertEqual(payload["error_kind"], "internal")
                # The fallback defaults are still populated.
                self.assertTrue(payload["message"].strip())
                self.assertTrue(payload["hint"].strip())

    def test_unknown_kind_never_invents_a_new_taxonomy_entry(self):
        errors.structured_error("brand_new_kind")
        self.assertNotIn("brand_new_kind", errors.ERROR_KINDS)

    def test_internal_error_does_not_leak_the_exception(self):
        marker = "SECRET-should-stay-in-the-log"
        exc = RuntimeError(f"boom: {marker}")
        payload = json.loads(errors.internal_error(exc, "some_tool")["content"][0]["text"])
        self.assertEqual(payload["error_kind"], "internal")
        self.assertNotIn(marker, json.dumps(payload))

    def test_internal_error_works_without_an_exception(self):
        payload = json.loads(errors.internal_error()["content"][0]["text"])
        self.assertEqual(payload["error_kind"], "internal")
        self.assertTrue(payload["hint"].strip())


class NoStackTraceTests(unittest.TestCase):
    """No error path may let a stack trace reach the response content."""

    def test_corpus_of_every_kind_has_no_stack_trace(self):
        corpus = []
        for kind in errors.ERROR_KINDS:
            corpus.append(errors.structured_error(kind)["content"][0]["text"])
            # Explicit arguments are the other path; cover it too.
            corpus.append(errors.structured_error(kind, f"detail {kind}", f"hint {kind}")["content"][0]["text"])
        corpus.append(errors.internal_error(RuntimeError("nested cause"))["content"][0]["text"])
        blob = "\n".join(corpus)
        for marker in _LEAK_MARKERS:
            self.assertNotIn(marker, blob)

    def test_source_has_no_format_exc_calls(self):
        """A ``format_exc(`` call site is how a stack would be stringified."""
        offenders = []
        for path in sorted(_PACKAGE_DIR.rglob("*.py")):
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                if "format_exc(" in line:
                    offenders.append(f"{path.name}:{lineno}")
        self.assertEqual(offenders, [], f"format_exc call sites: {offenders}")
