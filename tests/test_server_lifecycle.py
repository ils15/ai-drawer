"""Tests for the real MCP server startup/shutdown lifecycle.

Covers the reviewer's requested lifecycle cases:

a) no port binding before Fusion's main thread is ready,
b) a working ``/health`` endpoint once startup completed,
c) stopping the add-in while startup is still waiting for readiness,
d) stopping a running server and restarting it.

The Fusion main thread is simulated by a pump thread that services
``dispatch._flush_pending()`` exactly like the Custom Event handler
would, so the tests exercise the genuine readiness round-trip.
"""

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)

import http.client
import json
import queue
import socket
import threading
import time
import unittest
from unittest import mock

import settings
from fusion_bridge import dispatch, runtime
from lib import mcp_server as mcp_server_module


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _port_accepts(port, timeout=0.5):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _drain_pending():
    while not dispatch._pending.empty():
        dispatch._pending.get_nowait()


def _wait_until(predicate, timeout=15.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _health(port, timeout=5.0):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/health")
        response = conn.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        conn.close()


def _wait_for_health(port, timeout=15.0):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return _health(port)
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    raise AssertionError(f"/health never came up on port {port}: {last_error}")


class _MainThreadPump:
    """Stands in for the Fusion main thread by servicing the work queue."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            dispatch._flush_pending()
            self._stop.wait(0.02)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=5)


class ServerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self._original = {
            "port": settings.MCP_SERVER_PORT,
            "auto_connect": settings.MCP_AUTO_CONNECT,
            "callback": dispatch._callback_impl,
            "server": runtime._server,
        }
        settings.MCP_SERVER_PORT = _free_port()
        settings.MCP_AUTO_CONNECT = True
        runtime._server = None

        self._patches = [
            mock.patch.object(
                runtime.python_exec,
                "get_version_info",
                lambda *a, **kw: "test-version (lifecycle)",
            ),
            mock.patch.object(runtime, "log", lambda message, *a, **kw: None),
            mock.patch.object(
                dispatch.futil, "log", lambda message, *a, **kw: None
            ),
        ]
        for patcher in self._patches:
            patcher.start()

        dispatch._halt = threading.Event()
        dispatch._scheduler_active.clear()
        self._pump = None

    def tearDown(self):
        if self._pump is not None:
            self._pump.stop()
        runtime.stop()
        dispatch._halt = threading.Event()
        dispatch._scheduler_active.clear()
        dispatch._registered = False
        dispatch._callback_event = None
        dispatch._callback_impl = self._original["callback"]
        _drain_pending()
        with dispatch._inflight_lock:
            dispatch._inflight.clear()
        runtime._server = self._original["server"]
        settings.MCP_SERVER_PORT = self._original["port"]
        settings.MCP_AUTO_CONNECT = self._original["auto_connect"]
        for patcher in self._patches:
            patcher.stop()

    def _spy_server_start(self):
        calls = []
        original_start = mcp_server_module.MCPServer.start

        def spy(server_self):
            calls.append(server_self.port)
            return original_start(server_self)

        patcher = mock.patch.object(mcp_server_module.MCPServer, "start", spy)
        patcher.start()
        self._patches.append(patcher)
        return calls

    def _start_pump(self):
        self._pump = _MainThreadPump()
        self._pump.start()

    def _start_worker(self):
        worker = threading.Thread(
            target=runtime._server_start_worker, daemon=True
        )
        worker.start()
        return worker

    def test_a_no_binding_before_readiness(self):
        start_calls = self._spy_server_start()
        worker = self._start_worker()

        # Longer than wait_for_main_thread's 1s poll interval: the worker
        # is parked waiting for readiness, and must not have bound anything.
        time.sleep(1.5)
        self.assertIsNone(runtime._server)
        self.assertEqual(start_calls, [])
        self.assertFalse(
            _port_accepts(settings.MCP_SERVER_PORT),
            "the MCP port must not accept connections before readiness",
        )

        self._start_pump()
        self.assertTrue(_wait_until(lambda: runtime._server is not None))
        worker.join(timeout=15)
        self.assertFalse(worker.is_alive())
        self.assertTrue(runtime._server.is_running)
        self.assertEqual(start_calls, [settings.MCP_SERVER_PORT])

    def test_b_health_endpoint_after_readiness(self):
        worker = self._start_worker()
        self._start_pump()
        self.assertTrue(_wait_until(lambda: runtime._server is not None))
        worker.join(timeout=15)

        status, body = _wait_for_health(settings.MCP_SERVER_PORT)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertIsInstance(body["uptime_seconds"], int)

    def test_c_stop_while_waiting_for_readiness(self):
        start_calls = self._spy_server_start()
        worker = self._start_worker()
        time.sleep(1.2)
        self.assertIsNone(runtime._server)

        runtime.stop()
        worker.join(timeout=10)

        self.assertFalse(worker.is_alive())
        self.assertIsNone(runtime._server)
        self.assertEqual(start_calls, [])
        self.assertFalse(
            _port_accepts(settings.MCP_SERVER_PORT),
            "nothing may listen after stopping before readiness",
        )

    def test_d_stop_then_restart(self):
        self._start_pump()

        self.assertTrue(runtime.start())
        self.assertTrue(_wait_until(lambda: runtime._server is not None))
        first_server = runtime._server
        status, body = _wait_for_health(settings.MCP_SERVER_PORT)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

        runtime.stop()
        self.assertFalse(first_server.is_running)
        self.assertIsNone(runtime._server)
        self.assertFalse(_port_accepts(settings.MCP_SERVER_PORT))

        settings.MCP_SERVER_PORT = _free_port()
        self.assertTrue(runtime.start())
        self.assertTrue(_wait_until(lambda: runtime._server is not None))
        self.assertIsNot(runtime._server, first_server)
        status, body = _wait_for_health(settings.MCP_SERVER_PORT)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

        runtime.stop()
        self.assertIsNone(runtime._server)

    def test_old_start_worker_cannot_bind_after_restart(self):
        entered, release = threading.Event(), threading.Event()

        def delayed_readiness(**kwargs):
            entered.set()
            release.wait(5)
            return True

        with mock.patch.object(runtime, "wait_for_main_thread", delayed_readiness), \
                mock.patch.object(runtime, "_start_server") as start_server:
            old_shutdown = dispatch.get_shutdown_flag()
            worker = self._start_worker()
            try:
                self.assertTrue(entered.wait(2))
                runtime.stop()
                dispatch.init_main_thread_dispatch()
                self.assertIsNot(old_shutdown, dispatch.get_shutdown_flag())
                self.assertTrue(old_shutdown.is_set())
            finally:
                release.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
            start_server.assert_not_called()

    def test_queued_legacy_work_never_survives_stop_restart(self):
        result = []
        app = dispatch.get_app()
        with mock.patch.object(dispatch, "get_app", return_value=app), \
                mock.patch.object(app, "fireCustomEvent", return_value=True), \
                mock.patch.object(dispatch, "_callback_impl") as tool:
            worker = threading.Thread(target=lambda: result.append(
                dispatch.dispatch_to_main_thread({"params": {"name": "echo"},
                                                  "_request_key": "stop-test"})))
            worker.start()
            try:
                self.assertTrue(_wait_until(lambda: not dispatch._pending.empty()))
                runtime.stop()
                dispatch.init_main_thread_dispatch()
                dispatch._flush_pending()
            finally:
                worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertTrue(result[0]["isError"])
            self.assertTrue(dispatch._pending.empty())
            self.assertEqual(dispatch._inflight, {})
            tool.assert_not_called()

    def test_old_scheduler_tick_does_not_restart_timer_chain(self):
        old_shutdown = dispatch.get_shutdown_flag()
        runtime.stop()
        dispatch.init_main_thread_dispatch()
        with mock.patch.object(dispatch, "_fire_event_if_needed") as fire, \
                mock.patch.object(dispatch.threading, "Timer") as timer:
            dispatch._schedule_tick(old_shutdown)
            fire.assert_not_called()
            timer.assert_not_called()

    def test_submission_racing_with_stop_cannot_execute_after_restart(self):
        entered, release = threading.Event(), threading.Event()
        original_put = dispatch._pending.put
        result = []

        def delayed_put(envelope):
            entered.set()
            release.wait(5)
            original_put(envelope)

        app = dispatch.get_app()
        with mock.patch.object(dispatch, "get_app", return_value=app), \
                mock.patch.object(app, "fireCustomEvent", side_effect=lambda _: dispatch._flush_pending()), \
                mock.patch.object(dispatch, "_schedule_tick"), \
                mock.patch.object(dispatch._pending, "put", delayed_put), \
                mock.patch.object(dispatch, "_callback_impl") as tool:
            worker = threading.Thread(target=lambda: result.append(
                dispatch.dispatch_to_main_thread({"params": {"name": "echo"},
                                                  "_request_key": "late-submit"})))
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                runtime.stop()
                dispatch.init_main_thread_dispatch()
            finally:
                release.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertTrue(result[0]["isError"])
            tool.assert_not_called()

    def test_background_start_failure_only_signals_shutdown(self):
        with mock.patch.object(runtime, "wait_for_main_thread", return_value=True), \
                mock.patch.object(runtime, "_start_server", side_effect=RuntimeError("test failure")), \
                mock.patch.object(runtime, "stop_main_thread_dispatch") as unregister:
            worker = self._start_worker()
            worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertTrue(dispatch.get_shutdown_flag().is_set())
            unregister.assert_not_called()


if __name__ == "__main__":
    unittest.main()
