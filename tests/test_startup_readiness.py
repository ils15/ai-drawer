"""Tests for cold-start hardening.

Covers the two changes that prevent MCP clients from hanging while Fusion
is still starting up:

1. ``dispatch_to_main_thread`` returns a timeout error instead of blocking
   forever when the Fusion main thread never services a work item.
2. ``wait_for_main_thread`` gates server startup on a main-thread
   round-trip and gives up as soon as the add-in is shutting down.
"""

import threading
import time
import unittest

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)

import settings
from fusion_bridge import dispatch, runtime


class _FakeApp:
    """Stand-in with just enough surface for dispatch's event firing."""

    def fireCustomEvent(self, event_id):
        del event_id
        return True


class StartupPingTests(unittest.TestCase):
    def test_startup_ping_is_not_routed_as_tool(self):
        result = runtime.handle_any_tool({"params": {"name": "__startup_ping__"}})
        self.assertFalse(result.get("isError", False))
        self.assertEqual(result["content"][0]["text"], "ready")

    def test_wait_for_main_thread_short_circuits_on_main_thread(self):
        self.assertTrue(dispatch.wait_for_main_thread())

    def test_wait_for_main_thread_round_trips_from_background(self):
        ready = threading.Event()
        result = []

        def worker():
            result.append(
                dispatch.wait_for_main_thread(
                    poll_interval=0.1, shutdown=threading.Event()
                )
            )
            ready.set()

        worker_thread = threading.Thread(target=worker)
        worker_thread.start()

        # Act as the Fusion main thread: pump the queue until the worker
        # has completed its round-trip.
        deadline = time.monotonic() + 5
        while worker_thread.is_alive() and time.monotonic() < deadline:
            dispatch._flush_pending()
            time.sleep(0.02)
        worker_thread.join(timeout=5)

        self.assertFalse(worker_thread.is_alive())
        self.assertTrue(ready.is_set())
        self.assertEqual(result, [True])

    def test_wait_for_main_thread_exits_on_shutdown(self):
        shutdown = threading.Event()
        shutdown.set()
        done = threading.Event()

        def worker():
            dispatch.wait_for_main_thread(poll_interval=0.05, shutdown=shutdown)
            done.set()

        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()
        self.assertTrue(done.wait(timeout=2), "shutdown flag must end the wait")
        worker_thread.join(timeout=2)

    def test_wait_for_main_thread_aborts_when_shutdown_mid_wait(self):
        shutdown = threading.Event()
        done = threading.Event()
        result = []

        original_get_app = dispatch.get_app
        dispatch.get_app = lambda: _FakeApp()

        def worker():
            result.append(
                dispatch.wait_for_main_thread(
                    poll_interval=0.05, shutdown=shutdown
                )
            )
            done.set()

        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()
        time.sleep(0.15)  # let it enter the polling loop
        shutdown.set()
        self.assertTrue(done.wait(timeout=2))
        worker_thread.join(timeout=2)
        dispatch.get_app = original_get_app

        self.assertEqual(result, [False])


class DispatchTimeoutTests(unittest.TestCase):
    def setUp(self):
        self._original_get_app = dispatch.get_app
        self._original_timeout = settings.MCP_MAIN_THREAD_TIMEOUT
        dispatch.get_app = lambda: _FakeApp()
        settings.MCP_MAIN_THREAD_TIMEOUT = 0.2
        self._original_log = runtime.log
        runtime.log = lambda message, *a, **kw: None

    def tearDown(self):
        dispatch.get_app = self._original_get_app
        settings.MCP_MAIN_THREAD_TIMEOUT = self._original_timeout
        runtime.log = self._original_log

    def test_dispatch_returns_error_after_timeout(self):
        # No one pumps the queue, so the reply never arrives.
        results = []

        def worker():
            results.append(
                dispatch.dispatch_to_main_thread(
                    {"params": {"name": "some_tool", "arguments": {}}}
                )
            )

        worker_thread = threading.Thread(target=worker)
        worker_thread.start()
        worker_thread.join(timeout=5)

        self.assertFalse(worker_thread.is_alive(), "dispatch must not block forever")
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["isError"])
        self.assertIn("Timeout", results[0]["content"][0]["text"])

        # The abandoned envelope must not linger in the queue.
        self.assertTrue(dispatch._pending.empty())


if __name__ == "__main__":
    unittest.main()
