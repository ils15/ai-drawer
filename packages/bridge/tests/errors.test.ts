/**
 * Structured error envelope: every failure the LLM can observe is one JSON body
 * with error_kind/message/hint. These tests pin that contract for each
 * bridge-owned kind, and pin what must never be in it — stacks and exception
 * reprs stay in the log, not in the content.
 */

import { describe, expect, it } from "vitest";
import {
  BRIDGE_ERROR_KINDS,
  bridgeBugFailure,
  type ErrorEnvelope,
  forbiddenFailure,
  gateFailure,
  invalidArguments,
  protocolFailure,
  structuredError,
  type ToolResult,
  timeoutFailure,
  toolFailure,
  unreachableFailure,
} from "../src/errors.js";

/** Parses the envelope a constructor emitted, asserting the shape first. */
function envelope(result: ToolResult): ErrorEnvelope {
  expect(result.isError).toBe(true);
  expect(result.content).toHaveLength(1);
  expect(result.content[0]?.type).toBe("text");

  const parsed = JSON.parse((result.content[0] as { text: string }).text) as Record<string, unknown>;
  expect(Object.keys(parsed).sort()).toEqual(["error_kind", "hint", "message"]);
  expect(typeof parsed.error_kind).toBe("string");
  expect(typeof parsed.message).toBe("string");
  expect(typeof parsed.hint).toBe("string");
  expect((parsed.message as string).length).toBeGreaterThan(0);
  expect((parsed.hint as string).length).toBeGreaterThan(0);

  return parsed as unknown as ErrorEnvelope;
}

describe("every bridge kind emits one envelope with no exception detail", () => {
  it("carries its own kind, with a message and a hint, for all of them", () => {
    for (const kind of BRIDGE_ERROR_KINDS) {
      const body = envelope(structuredError(kind));
      expect(body.error_kind, kind).toBe(kind);
    }
  });

  it("degrades an unknown kind to bridge_bug instead of raising", () => {
    // A bad error name must never become a second failure while reporting one.
    const body = envelope(structuredError("no_such_kind" as never));
    expect(body.error_kind).toBe("bridge_bug");
  });

  it("falls back to the per-kind defaults when message and hint are empty", () => {
    const body = envelope(structuredError("tool_failed", "", "  "));
    expect(body.message).not.toBe("");
    expect(body.hint).not.toBe("");
  });

  it("keeps a caller-supplied message and hint verbatim", () => {
    const body = envelope(structuredError("protocol_error", "reply was a poem", "ask for prose instead"));
    expect(body.message).toBe("reply was a poem");
    expect(body.hint).toBe("ask for prose instead");
  });

  it("emits indented JSON, matching the add-in's structured_error framing", () => {
    const text = structuredError("tool_failed").content[0]?.text ?? "";
    expect(text).toBe(
      `{\n  "error_kind": "tool_failed",\n  "message": "The tool failed inside Fusion.",\n  "hint": "Read the message: it says what the tool could not do. Fix the named cause and retry; if it repeats, call fusion_health."\n}`,
    );
  });

  it("leaks no stack trace, exception repr or internal identifier", () => {
    const results: ToolResult[] = [
      structuredError("tool_failed"),
      unreachableFailure("127.0.0.1", 6111, "connect ECONNREFUSED 127.0.0.1:6111"),
      forbiddenFailure("127.0.0.1", 6111, "upstream rejected the request"),
      bridgeBugFailure("upstream returned HTTP 405 at http://127.0.0.1:6111/mcp"),
      protocolFailure("capture_viewport", "unexpected Content-Type 'text/html'"),
    ];
    for (const result of results) {
      expect(JSON.stringify(result)).not.toMatch(/Traceback|File "|at Object\.|<unknown>|str\(/);
    }
  });
});

describe("gateFailure maps each refusal reason onto its own kind", () => {
  it("blocked-hard becomes blocked_hard and names the tool", () => {
    const body = envelope(gateFailure("execute_python", "blocked-hard"));
    expect(body.error_kind).toBe("blocked_hard");
    expect(body.message).toContain("execute_python");
    expect(body.message).toContain("security policy");
  });

  it("pending-wave3 becomes pending_wave3", () => {
    const body = envelope(gateFailure("extrude", "pending-wave3"));
    expect(body.error_kind).toBe("pending_wave3");
    expect(body.message).toContain("extrude");
    expect(body.message).toContain("not available yet");
  });

  it("not-allowed becomes not_allowed", () => {
    const body = envelope(gateFailure("definitely_not_a_tool", "not-allowed"));
    expect(body.error_kind).toBe("not_allowed");
    expect(body.message).toContain("definitely_not_a_tool");
  });
});

describe("invalidArguments puts the failing field path in the hint", () => {
  it("reports kind invalid_arguments and names the tool", () => {
    const body = envelope(
      invalidArguments("new_document", [
        { path: ["design_type"], message: 'Invalid option: expected one of "parametric"|"direct"' },
      ]),
    );
    expect(body.error_kind).toBe("invalid_arguments");
    expect(body.message).toContain("new_document");
  });

  it("carries each offending field path, never a stack", () => {
    const body = envelope(
      invalidArguments("set_viewport", [
        { path: ["camera", "eye", "x"], message: "Expected number, received string" },
        { path: ["zoom"], message: "Number must be greater than or equal to 0.01" },
      ]),
    );
    expect(body.hint).toContain("camera.eye.x");
    expect(body.hint).toContain("zoom");
    expect(body.hint).not.toMatch(/at Object\.|Traceback/);
  });

  it("falls back to the tool name when the failure is at the root", () => {
    const body = envelope(invalidArguments("export_document", [{ path: [], message: 'Unrecognized key: "format"' }]));
    expect(body.hint).toContain("export_document");
  });

  it("still names the tool when zod reported nothing", () => {
    const body = envelope(invalidArguments("get_viewport", []));
    expect(body.error_kind).toBe("invalid_arguments");
    expect(body.message).toContain("get_viewport");
    expect(body.hint.length).toBeGreaterThan(0);
  });
});

describe("wire tiers keep their distinct kinds and contracts", () => {
  it("unreachableFailure stays tier (c), naming the endpoint tried", () => {
    const body = envelope(unreachableFailure("127.0.0.1", 6111));
    expect(body.error_kind).toBe("addin_unreachable");
    expect(body.message).toContain("Fusion 360 is not reachable at 127.0.0.1:6111.");
    expect(body.hint).toContain("AutodeskFusionMCP");
    expect(body.hint).toContain("FUSION_MCP_HOST");
  });

  it("unreachableFailure appends the upstream detail", () => {
    const body = envelope(unreachableFailure("127.0.0.1", 6111, "connection refused"));
    expect(body.message).toContain("connection refused");
  });

  it("timeoutFailure gets its own kind and the budget it exceeded", () => {
    const body = envelope(timeoutFailure("127.0.0.1", 6111, 60_000, "request exceeded the budget"));
    expect(body.error_kind).toBe("addin_timeout");
    expect(body.message).toContain("did not answer within 60000 ms");
    expect(body.message).toContain("127.0.0.1:6111");
  });

  it("forbiddenFailure attributes the gate to the Origin header, not the host", () => {
    const body = envelope(forbiddenFailure("127.0.0.1", 6111));
    expect(body.error_kind).toBe("addin_forbidden");
    expect(body.message).toContain("The Fusion add-in at 127.0.0.1:6111 rejected the request (HTTP 403).");
    expect(body.message).toContain("The add-in gates on the Origin header, not the host.");
  });

  it("forbiddenFailure names the fixed loopback origin and clears FUSION_MCP_HOST", () => {
    const body = envelope(forbiddenFailure("127.0.0.1", 6111, "upstream rejected the request"));
    expect(body.message).toContain("loopback origin http://127.0.0.1:6111");
    expect(body.message).toContain("FUSION_MCP_HOST cannot cause this.");
    expect(body.message).toContain("upstream rejected the request");
    expect(body.message).not.toContain("make sure it matches the host");
  });

  it("forbiddenFailure points at the two real causes", () => {
    const body = envelope(forbiddenFailure("127.0.0.1", 6111));
    expect(body.message).toContain("a non-bridge client");
    expect(body.message).toContain("allowed_origins");
    expect(body.message).toContain("lib/mcp_server.py");
  });

  it("bridgeBugFailure reports the contract violation as impossible-in-release", () => {
    const body = envelope(bridgeBugFailure("upstream returned HTTP 406 at http://127.0.0.1:6111/mcp"));
    expect(body.error_kind).toBe("bridge_bug");
    expect(body.message).toContain("HTTP 406");
    expect(body.message).toContain("should be impossible in a released build");
  });

  it("protocolFailure names the tool and keeps the decode failure out of the message", () => {
    const body = envelope(protocolFailure("capture_viewport", "SSE stream ended without a message frame"));
    expect(body.error_kind).toBe("protocol_error");
    expect(body.message).toContain("capture_viewport");
    expect(body.message).toContain("SSE stream ended without a message frame");
  });

  it("toolFailure delegates to the same envelope", () => {
    const body = envelope(toolFailure("tool_failed", "Tool 'extrude' failed (code -32603)."));
    expect(body.error_kind).toBe("tool_failed");
    expect(body.message).toBe("Tool 'extrude' failed (code -32603).");
  });
});
