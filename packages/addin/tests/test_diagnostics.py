"""Tests for the thread-safe diagnostics counters and the snapshot whitelist.

Two properties matter for the Phase-2 reliability work:

* the counters are correct under real concurrency.  The main-thread dispatcher
  serves up to 16 concurrent client slots, and a lost increment would silently
  underreport failures -- so the counts are checked against an exact expected
  total after a burst across that many threads.
* the snapshot cannot leak.  ``SNAPSHOT_FIELDS`` is the entire contract: file
  paths, environment variables, exception messages, script names, and ``adsk``
  objects never enter the payload, so a diagnostics endpoint can hand it to a
  client without filtering.  The tests assert the whitelist is closed *and*
  that the sensitive categories are absent from the serialized output.
"""

import json
import os
import pathlib
import threading
import unittest

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)

from fusion_bridge import diagnostics, errors

# Main-thread dispatch serves up to this many concurrent client slots.
SLOTS = 16
# Divisible by len(ERROR_KINDS) so each kind gets an exactly equal share and
# the per-kind assertion is exact rather than approximate.
CALLS_PER_SLOT = 240


class CounterTests(unittest.TestCase):
    """``record_call`` / ``record_error`` must count exactly, even in parallel."""

    def setUp(self):
        diagnostics.reset()

    def test_record_call_increments_only_the_total(self):
        diagnostics.record_call()
        diagnostics.record_call()
        snap = diagnostics.snapshot()
        self.assertEqual(snap["tool_calls"], 2)
        self.assertEqual(snap["tool_errors"], 0)

    def test_record_error_counts_total_and_kind(self):
        diagnostics.record_error("not_found")
        diagnostics.record_error("not_found")
        diagnostics.record_error("internal")
        snap = diagnostics.snapshot()
        self.assertEqual(snap["tool_errors"], 3)
        self.assertEqual(snap["error_kinds"]["not_found"], 2)
        self.assertEqual(snap["error_kinds"]["internal"], 1)

    def test_unknown_kind_increments_total_without_extending_taxonomy(self):
        diagnostics.record_error("this_kind_does_not_exist")
        snap = diagnostics.snapshot()
        self.assertEqual(snap["tool_errors"], 1)
        # The per-kind dict stays closed: an unclassifiable failure is still a
        # failure, but never becomes a new key a client could see.
        self.assertEqual(set(snap["error_kinds"]), set(errors.ERROR_KINDS))
        self.assertNotIn("this_kind_does_not_exist", snap["error_kinds"])

    def test_reset_zeroes_every_counter(self):
        diagnostics.record_error("io_failure")
        diagnostics.record_call()
        diagnostics.reset()
        snap = diagnostics.snapshot()
        self.assertEqual(snap["tool_calls"], 0)
        self.assertEqual(snap["tool_errors"], 0)
        self.assertEqual(sum(snap["error_kinds"].values()), 0)

    def test_counters_are_exact_under_concurrent_dispatch(self):
        # A barrier so every thread hits the counters at (nearly) the same
        # instant; that is what makes a lost increment observable.
        barrier = threading.Barrier(SLOTS)
        per_slot_counts = []

        def worker():
            barrier.wait()
            local_calls = 0
            local_errors = 0
            for i in range(CALLS_PER_SLOT):
                diagnostics.record_call()
                diagnostics.record_error(errors.ERROR_KINDS[i % len(errors.ERROR_KINDS)])
                local_calls += 1
                local_errors += 1
            per_slot_counts.append((local_calls, local_errors))

        threads = [threading.Thread(target=worker) for _ in range(SLOTS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        expected = SLOTS * CALLS_PER_SLOT
        self.assertEqual(sum(c for c, _ in per_slot_counts), expected)
        snap = diagnostics.snapshot()
        self.assertEqual(snap["tool_calls"], expected)
        self.assertEqual(snap["tool_errors"], expected)
        # Each kind saw an equal share, so no increment was dropped or
        # double-counted on the per-kind dict either.
        share = expected // len(errors.ERROR_KINDS)
        for kind in errors.ERROR_KINDS:
            self.assertEqual(snap["error_kinds"][kind], share)


class SnapshotWhitelistTests(unittest.TestCase):
    """The snapshot exposes counts and flags only -- never sensitive data."""

    def setUp(self):
        diagnostics.reset()

    def test_snapshot_exposes_exactly_the_whitelisted_fields(self):
        snap = diagnostics.snapshot()
        self.assertEqual(set(snap), set(diagnostics.SNAPSHOT_FIELDS))

    def test_snapshot_field_types_are_public_safe(self):
        snap = diagnostics.snapshot()
        for flag in ("ready", "dispatch_active", "document_open"):
            self.assertIsInstance(snap[flag], bool)
        self.assertIsInstance(snap["tool_calls"], int)
        self.assertIsInstance(snap["tool_errors"], int)
        self.assertIsInstance(snap["tool_count"], int)
        self.assertIsInstance(snap["tool_names"], list)
        for name in snap["tool_names"]:
            self.assertIsInstance(name, str)
        # Per-kind counts are ints keyed only by taxonomy members.
        self.assertEqual(set(snap["error_kinds"]), set(errors.ERROR_KINDS))
        for count in snap["error_kinds"].values():
            self.assertIsInstance(count, int)

    def test_error_kinds_keys_stay_closed_under_bogus_input(self):
        # A caller cannot inject a key that would smuggle text into the payload.
        for bogus in ("/etc/passwd", "HOME", "Traceback (most recent", "adsk.fusion"):
            diagnostics.record_error(bogus)
        snap = diagnostics.snapshot()
        self.assertEqual(set(snap["error_kinds"]), set(errors.ERROR_KINDS))
        self.assertEqual(snap["tool_errors"], 4)

    def test_snapshot_serializes_and_carries_no_sensitive_material(self):
        diagnostics.record_call()
        diagnostics.record_error("network_failure")
        blob = json.dumps(diagnostics.snapshot())

        # No stack traces or exception-string markers.
        for marker in ("Traceback", "format_exc", "Exception", "Error:"):
            self.assertNotIn(marker, blob)

        # No environment values leak (the sensitive part of the environment).
        for value in os.environ.values():
            if len(value) >= 4:  # skip trivial values that could collide
                self.assertNotIn(value, blob)

        # No ``adsk`` objects or module references.
        self.assertNotIn("adsk", blob)
        self.assertNotIn("<adsk", blob)

        # No source paths from this repo.
        for path in (__file__, os.path.abspath(__file__), os.getcwd()):
            self.assertNotIn(path, blob)

    def test_module_source_reads_no_environment_or_script_paths(self):
        """Structural check: diagnostics cannot leak what it never reads."""
        source = pathlib.Path(diagnostics.__file__).read_text()
        for forbidden in ("os.environ", "getenv", "__file__", "format_exc"):
            self.assertNotIn(forbidden, source)

    def test_tool_names_carry_no_file_paths(self):
        snap = diagnostics.snapshot()
        for name in snap["tool_names"]:
            self.assertNotIn(os.sep, name)
            self.assertNotIn("/", name)


if __name__ == "__main__":
    unittest.main()
