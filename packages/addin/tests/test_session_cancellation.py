"""Legacy cancellation must never target another client's queued Fusion work."""

import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import _fusion_test_bootstrap  # noqa: F401
from test_http_protocols import HTTPFixture, sse_message

import settings
from fusion_bridge import dispatch
from lib.mcp_server import LEGACY_PROTOCOL_VERSIONS


class SessionCancellationTests(HTTPFixture, unittest.TestCase):
    def setUp(self):
        self.executed = []
        self.workers = []
        dispatch._halt.clear()
        for target, attribute, value in (
            (dispatch, "get_app", lambda: SimpleNamespace(fireCustomEvent=lambda _: True)),
            (dispatch, "_callback_impl", self.execute),
            (dispatch.futil, "log", lambda *a, **kw: None),
            (settings, "MCP_MAIN_THREAD_TIMEOUT", 5),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.start_server(tool_handlers={"echo": dispatch.dispatch_to_main_thread})

    def tearDown(self):
        dispatch._flush_pending()
        for worker in self.workers:
            worker.join(timeout=6)
        self.assertTrue(dispatch._pending.empty())
        self.assertEqual(dispatch._inflight, {})

    def execute(self, call):
        text = call["params"]["arguments"]["text"]
        self.executed.append(text)
        return {"content": [{"type": "text", "text": text}]}

    def headers(self, version, session=None):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": version}
        if session is not None:
            headers["Mcp-Session-Id"] = session
        return headers

    def initialize(self, version):
        response = self.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": version, "capabilities": {},
            "clientInfo": {"name": "cancellation-test", "version": "1"},
        }}, self.headers(version))
        session = response.getheader("Mcp-Session-Id")
        self.assertEqual(json.loads(response.read())["result"]["protocolVersion"], version)
        self.assertTrue(session)
        response = self.send({"jsonrpc": "2.0", "method": "notifications/initialized"},
                             self.headers(version, session))
        self.assertEqual((response.status, response.read()), (202, b""))
        return session

    def queued_call(self, version, session, text, request_id=7, queued=True):
        connection = self.connect()
        result, done = {}, threading.Event()

        def worker():
            try:
                response = self.send({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                                      "params": {"name": "echo", "arguments": {"text": text}}},
                                     self.headers(version, session), connection)
                result.update(sse_message(response)["result"])
                response.read()  # Also check the HTTP body terminates.
            except Exception as exc:
                result["exception"] = repr(exc)
            finally:
                done.set()

        thread = threading.Thread(target=worker, daemon=True)
        self.workers.append(thread)
        thread.start()
        if queued:
            def is_queued():
                with dispatch._pending.mutex:
                    return any(e["payload"]["params"]["arguments"].get("text") == text
                               for e in dispatch._pending.queue)
            self.wait_for(is_queued)
        return result, done

    def cancel(self, version, session, request_id=7):
        response = self.send({"jsonrpc": "2.0", "method": "notifications/cancelled",
                              "params": {"requestId": request_id}}, self.headers(version, session))
        self.assertEqual((response.status, response.read()), (202, b""))

    def test_same_id_in_two_initialized_sessions_cancels_only_sender(self):
        for version in LEGACY_PROTOCOL_VERSIONS:
            with self.subTest(version=version):
                a, b = self.initialize(version), self.initialize(version)
                result_a, done_a = self.queued_call(version, a, "A")
                result_b, done_b = self.queued_call(version, b, "B")
                self.cancel(version, a)
                self.assertTrue(done_a.wait(2))
                self.assertTrue(result_a.get("isError"), result_a)
                self.assertIn("never executed", result_a["content"][0]["text"])
                self.assertFalse(done_b.is_set())
                dispatch._flush_pending()
                self.assertTrue(done_b.wait(2))
                self.assertEqual(result_b, {"content": [{"type": "text", "text": "B"}]})
        self.assertEqual(self.executed, ["B"] * len(LEGACY_PROTOCOL_VERSIONS))

    def test_missing_or_foreign_session_cannot_cancel_work(self):
        version = LEGACY_PROTOCOL_VERSIONS[0]
        session = self.initialize(version)
        result, done = self.queued_call(version, session, "owned")
        anonymous, anonymous_done = self.queued_call(version, None, "anonymous")
        self.cancel(version, None)
        self.cancel(version, "unknown-session")
        self.assertFalse(done.is_set())
        self.assertFalse(anonymous_done.is_set())
        dispatch._flush_pending()
        self.assertTrue(done.wait(2))
        self.assertTrue(anonymous_done.wait(2))
        self.assertEqual(self.executed, ["owned", "anonymous"])
        self.assertNotIn("exception", result)
        self.assertNotIn("exception", anonymous)

    def test_duplicate_id_cannot_replace_original_cancellation_target(self):
        version = LEGACY_PROTOCOL_VERSIONS[0]
        session = self.initialize(version)
        original, original_done = self.queued_call(version, session, "original")
        duplicate, duplicate_done = self.queued_call(version, session, "duplicate", queued=False)
        self.assertTrue(duplicate_done.wait(2))
        self.assertTrue(duplicate.get("isError"), duplicate)
        self.assertIn("already in flight", duplicate["content"][0]["text"])
        self.cancel(version, session)
        self.assertTrue(original_done.wait(2))
        self.assertIn("never executed", original["content"][0]["text"])
        self.assertEqual(self.executed, [])

    def test_server_instances_do_not_share_cancellation_targets(self):
        version = LEGACY_PROTOCOL_VERSIONS[0]
        session = self.initialize(version)
        original, original_done = self.queued_call(version, session, "first-server")
        self.start_server(tool_handlers={"echo": dispatch.dispatch_to_main_thread})
        other, other_done = self.queued_call(version, session, "second-server")
        self.cancel(version, session)
        self.assertTrue(other_done.wait(2))
        self.assertTrue(other.get("isError"), other)
        self.assertFalse(original_done.is_set())
        dispatch._flush_pending()
        self.assertTrue(original_done.wait(2))
        self.assertEqual(original, {"content": [{"type": "text", "text": "first-server"}]})
        self.assertEqual(self.executed, ["first-server"])
