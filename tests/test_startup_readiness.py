"""Tests for cold-start hardening.

Covers the changes that prevent MCP clients from hanging while Fusion
is still starting up:

1. ``dispatch_to_main_thread`` returns a timeout error instead of blocking
   forever when the Fusion main thread never services a work item, and
   distinguishes queued work (cancelled, safe to retry) from work already
   executing on the Fusion main thread (may still complete, must not be
   blindly retried).
2. ``wait_for_main_thread`` gates server startup on a main-thread
   round-trip and gives up as soon as the add-in is shutting down.
3. MCP ``notifications/cancelled`` cancels a queued tools/call.
"""

import http.client
import json
import queue
import socket
import threading
import time
import unittest
import urllib.request

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)

import settings
import lib.mcp_server
from fusion_bridge import dispatch, runtime


class _FakeApp:
    """Stand-in with just enough surface for dispatch's event firing."""

    def fireCustomEvent(self, event_id):
        del event_id
        return True


def _wait_for_inflight_state(request_id, state, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        envelope = dispatch._inflight.get(request_id)
        if envelope is not None and envelope["_state"] == state:
            return True
        time.sleep(0.01)
    return False


class StartupPingTests(unittest.TestCase):
    def test_startup_ping_is_not_routed_as_tool(self):
        result = runtime.handle_any_tool({"params": {"name": "__startup_ping__"}})
        self.assertFalse(result.get("isError", False))
        self.assertEqual(result["content"][0]["text"], "ready")

    def test_startup_ping_handled_without_tool_handler(self):
        original_cb = dispatch._callback_impl
        original_futil_log = dispatch.futil.log
        dispatch._callback_impl = None
        logged = []
        dispatch.futil.log = lambda message, *a, **kw: logged.append(message)
        try:
            reply = queue.Queue(maxsize=1)
            envelope = dispatch._new_envelope(
                {"params": {"name": "__startup_ping__"}}, reply
            )
            dispatch._pending.put(envelope)
            dispatch._flush_pending()
            result = reply.get_nowait()
        finally:
            dispatch._callback_impl = original_cb
            dispatch.futil.log = original_futil_log

        self.assertEqual(result["content"][0]["text"], "ready")
        self.assertFalse(result.get("isError", False))
        self.assertEqual(envelope["_state"], "done")
        self.assertFalse(
            any("not initialized" in str(entry) for entry in logged),
            f"ping must not depend on the tool handler: {logged}",
        )

    def test_wait_for_main_thread_short_circuits_on_main_thread(self):
        self.assertTrue(dispatch.wait_for_main_thread())

    def test_wait_for_main_thread_round_trips_from_background(self):
        ready = threading.Event()
        result = []
        original_futil_log = dispatch.futil.log
        logged = []
        dispatch.futil.log = lambda message, *a, **kw: logged.append(message)

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
        dispatch.futil.log = original_futil_log

        self.assertFalse(worker_thread.is_alive())
        self.assertTrue(ready.is_set())
        self.assertEqual(result, [True])
        self.assertFalse(
            any("not initialized" in str(entry) for entry in logged),
            f"readiness round-trip must not log tool-routing errors: {logged}",
        )

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
        text = results[0]["content"][0]["text"]
        # Still queued when the timeout hit, so the request was cancelled
        # before execution and the client may safely retry.
        for fragment in ("cancelled", "never executed", "Safe to retry"):
            self.assertIn(fragment, text)

        # The abandoned envelope must not linger in the queue.
        self.assertTrue(dispatch._pending.empty())

    def test_dispatch_queued_timeout_cancels(self):
        # Timed out while still queued: the request was cancelled before
        # execution, so the client may safely retry.
        results = []

        def worker():
            results.append(
                dispatch.dispatch_to_main_thread(
                    {
                        "params": {"name": "some_tool", "arguments": {}},
                        "_request_key": "queued-timeout",
                    }
                )
            )

        worker_thread = threading.Thread(target=worker)
        worker_thread.start()
        self.assertTrue(_wait_for_inflight_state("queued-timeout", "queued"))
        worker_thread.join(timeout=5)

        self.assertFalse(worker_thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["isError"])
        text = results[0]["content"][0]["text"]
        for fragment in ("cancelled", "never executed", "Safe to retry"):
            self.assertIn(fragment, text)
        self.assertNotIn("still executing", text)
        self.assertTrue(dispatch._pending.empty())
        # Already timed out and deregistered: nothing left to cancel.
        self.assertFalse(dispatch.cancel_request("queued-timeout"))

    def test_dispatch_running_timeout_reports_may_complete(self):
        # Timed out while the Fusion main thread is mid-execution: the
        # client must be told the operation may still complete.
        entered = threading.Event()
        release = threading.Event()

        def slow_handler(call_data):
            entered.set()
            release.wait(timeout=5)
            return {"content": [{"type": "text", "text": "slow-done"}]}

        original_cb = dispatch._callback_impl
        dispatch._callback_impl = slow_handler
        settings.MCP_MAIN_THREAD_TIMEOUT = 0.5
        results = []

        def worker():
            results.append(
                dispatch.dispatch_to_main_thread(
                    {
                        "params": {"name": "slow_tool", "arguments": {}},
                        "_request_key": "running-timeout",
                    }
                )
            )

        worker_thread = threading.Thread(target=worker)
        worker_thread.start()

        pump_thread = threading.Thread(target=dispatch._flush_pending)
        pump_thread.start()

        self.assertTrue(_wait_for_inflight_state("running-timeout", "running"))
        self.assertTrue(entered.wait(timeout=5), "slow tool must be executing")
        worker_thread.join(timeout=5)

        self.assertFalse(worker_thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["isError"])
        text = results[0]["content"][0]["text"]
        for fragment in ("still executing", "may complete", "Do NOT blindly retry"):
            self.assertIn(fragment, text)
        self.assertNotIn("aborted", text)
        self.assertNotIn("Safe to retry", text)

        release.set()
        pump_thread.join(timeout=5)
        dispatch._callback_impl = original_cb

    def test_cancel_queued_request(self):
        results = []

        def worker():
            results.append(
                dispatch.dispatch_to_main_thread(
                    {
                        "params": {"name": "some_tool", "arguments": {}},
                        "_request_key": "cancel-queued",
                    }
                )
            )

        settings.MCP_MAIN_THREAD_TIMEOUT = 30.0
        worker_thread = threading.Thread(target=worker)
        worker_thread.start()
        self.assertTrue(_wait_for_inflight_state("cancel-queued", "queued"))

        self.assertTrue(dispatch.cancel_request("cancel-queued"))
        worker_thread.join(timeout=5)

        self.assertFalse(worker_thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["isError"])
        text = results[0]["content"][0]["text"]
        for fragment in ("cancelled", "never executed", "Safe to retry"):
            self.assertIn(fragment, text)
        self.assertTrue(dispatch._pending.empty())
        self.assertFalse(dispatch.cancel_request("cancel-queued"))

    def test_cancel_running_request_returns_false(self):
        entered = threading.Event()
        release = threading.Event()

        def slow_handler(call_data):
            entered.set()
            release.wait(timeout=5)
            return {"content": [{"type": "text", "text": "slow-done"}]}

        original_cb = dispatch._callback_impl
        dispatch._callback_impl = slow_handler
        settings.MCP_MAIN_THREAD_TIMEOUT = 30.0
        results = []

        def worker():
            results.append(
                dispatch.dispatch_to_main_thread(
                    {
                        "params": {"name": "slow_tool", "arguments": {}},
                        "_request_key": "cancel-running",
                    }
                )
            )

        worker_thread = threading.Thread(target=worker)
        worker_thread.start()

        pump_thread = threading.Thread(target=dispatch._flush_pending)
        pump_thread.start()

        self.assertTrue(_wait_for_inflight_state("cancel-running", "running"))
        self.assertFalse(
            dispatch.cancel_request("cancel-running"),
            "running Fusion work must not be cancellable",
        )

        release.set()
        pump_thread.join(timeout=5)
        worker_thread.join(timeout=5)
        self.assertEqual(
            results, [{"content": [{"type": "text", "text": "slow-done"}]}]
        )
        self.assertTrue(dispatch._pending.empty())
        dispatch._callback_impl = original_cb


class CancelNotificationHttpTests(unittest.TestCase):
    """End-to-end: notifications/cancelled wakes a queued tools/call over HTTP."""

    def setUp(self):
        self._original_get_app = dispatch.get_app
        self._original_cb = dispatch._callback_impl
        self._original_timeout = settings.MCP_MAIN_THREAD_TIMEOUT
        self._original_log = runtime.log
        dispatch.get_app = lambda: _FakeApp()
        settings.MCP_MAIN_THREAD_TIMEOUT = 30.0
        runtime.log = lambda message, *a, **kw: None

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]

        self.server = lib.mcp_server.MCPServer(
            port=self.port,
            tools=[
                {
                    "name": "slow_tool",
                    "description": "test tool",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ],
            tool_handlers={"slow_tool": dispatch.dispatch_to_main_thread},
            log_callback=lambda message: None,
        )
        self.server.start()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/mcp", json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "cancel-test", "version": "1"}},
        }), {"Content-Type": "application/json", "Accept": "application/json"})
        response = conn.getresponse()
        self.session_id = response.getheader("Mcp-Session-Id")
        response.read()
        conn.close()

    def tearDown(self):
        self.server.stop()
        dispatch.get_app = self._original_get_app
        dispatch._callback_impl = self._original_cb
        settings.MCP_MAIN_THREAD_TIMEOUT = self._original_timeout
        runtime.log = self._original_log
        while not dispatch._pending.empty():
            dispatch._pending.get_nowait()
        with dispatch._inflight_lock:
            dispatch._inflight.clear()

    def _post(self, body, timeout=10, read_data=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            conn.request(
                "POST",
                "/mcp",
                body=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "Mcp-Session-Id": self.session_id,
                },
            )
            response = conn.getresponse()
            status = response.status
            data = None
            if read_data:
                # SSE responses have no Content-Length; read the first
                # event line instead of waiting for EOF.
                while True:
                    line = response.readline()
                    if not line:
                        break
                    text_line = line.decode("utf-8")
                    if text_line.startswith("data:"):
                        data = text_line[len("data:") :].strip()
                        break
            return status, data
        finally:
            conn.close()

    def test_cancelled_notification_wakes_queued_tools_call(self):
        result = {}

        def call_tool():
            result["response"] = self._post(
                {
                    "jsonrpc": "2.0",
                    "id": "cancel-e2e",
                    "method": "tools/call",
                    "params": {"name": "slow_tool", "arguments": {}},
                }
            )

        worker_thread = threading.Thread(target=call_tool)
        worker_thread.start()
        self.assertTrue(
            _wait_for_inflight_state(self.server._request_key("cancel-e2e", self.session_id), "queued"),
            "server must register the call as cancellable",
        )

        cancel_status, _ = self._post(
            {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": "cancel-e2e"},
            },
            read_data=False,
        )
        self.assertEqual(cancel_status, 202)

        worker_thread.join(timeout=10)
        self.assertFalse(worker_thread.is_alive())
        body = result["response"][1]
        self.assertIn("cancelled", body)
        self.assertIn("Safe to retry", body)


if __name__ == "__main__":
    unittest.main()
