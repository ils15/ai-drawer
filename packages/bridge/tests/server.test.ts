/**
 * End-to-end server tests. The bridge is driven through a real SDK Client over
 * a linked in-memory transport, so the full protocol path — initialize,
 * tools/list, tools/call — is exercised exactly as OpenCode would exercise it.
 */

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { CallToolResult, Tool } from "@modelcontextprotocol/sdk/types.js";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { resetSecuritySink, type SecurityEvent, setSecuritySink } from "../src/allowlist.js";
import type { ResolvedHost } from "../src/config.js";
import { resetResolvedHost } from "../src/config.js";
import { createBridgeServer } from "../src/server.js";
import { FakeAddin } from "./fake-addin.js";

interface Harness {
  bridge: Awaited<ReturnType<typeof createBridgeServer>>;
  client: Client;
  close: () => Promise<void>;
}

/** The envelope the bridge emits: error_kind + message + hint, in that order. */
interface ErrorEnvelope {
  readonly error_kind: string;
  readonly message: string;
  readonly hint: string;
}

/** Parses a tool result's content, asserting it is one structured error envelope. */
function errorEnvelope(result: CallToolResult): ErrorEnvelope {
  expect(result.isError).toBe(true);
  expect(result.content).toHaveLength(1);
  expect(result.content[0]?.type).toBe("text");
  const body = JSON.parse((result.content[0] as { text: string }).text) as Record<string, unknown>;
  expect(Object.keys(body).sort()).toEqual(["error_kind", "hint", "message"]);
  expect((body.message as string).length).toBeGreaterThan(0);
  expect((body.hint as string).length).toBeGreaterThan(0);
  return body as unknown as ErrorEnvelope;
}

async function harness(): Promise<Harness> {
  const bridge = await createBridgeServer();
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await bridge.server.connect(serverTransport);

  const client = new Client({ name: "test-client", version: "1.0.0" }, { capabilities: {} });
  await client.connect(clientTransport);

  return {
    bridge,
    client,
    close: async () => {
      await client.close();
      await bridge.close();
    },
  };
}

describe("bridge server", () => {
  let addin: FakeAddin;
  let events: SecurityEvent[] = [];
  let envHost: string | undefined;
  let envPort: string | undefined;

  beforeEach(async () => {
    addin = new FakeAddin({ mode: "json" });
    await addin.start();
    envHost = process.env.FUSION_MCP_HOST;
    envPort = process.env.FUSION_MCP_PORT;
    process.env.FUSION_MCP_HOST = "127.0.0.1";
    process.env.FUSION_MCP_PORT = String(addin.port);
    resetResolvedHost();
    events = [];
    setSecuritySink((event) => events.push(event));
  });

  afterEach(async () => {
    resetSecuritySink();
    if (envHost === undefined) delete process.env.FUSION_MCP_HOST;
    else process.env.FUSION_MCP_HOST = envHost;
    if (envPort === undefined) delete process.env.FUSION_MCP_PORT;
    else process.env.FUSION_MCP_PORT = envPort;
    resetResolvedHost();
    await addin.close();
  });

  it("resolves the add-in endpoint from the environment", async () => {
    const bridge = await createBridgeServer();
    const endpoint: ResolvedHost = bridge.monitor.endpoint;
    expect(endpoint.host).toBe("127.0.0.1");
    expect(endpoint.port).toBe(addin.port);
    expect(endpoint.source).toBe("env");
  });

  it("initializes once at startup and negotiates upstream", async () => {
    const bridge = await createBridgeServer();
    // The initialize is best-effort; give it a tick to land.
    await delay(50);
    const pings = addin.requests.filter((request) => request.body.includes('"initialize"'));
    expect(pings.length).toBe(1);
    bridge.close && (await bridge.close());
  });

  it("filters BLOCKED_HARD and unlisted tools out of tools/list", async () => {
    const harness_ = await harness();
    try {
      const { tools }: { tools: Tool[] } = await harness_.client.listTools();
      const names = tools.map((tool) => tool.name);

      expect(names).not.toContain("execute_python");
      expect(names).not.toContain("apply_material");
      expect(names).toContain("capture_viewport");
      expect(names).toContain("fusion_health");
      // A promoted Wave-2 tool must survive the filter, not just Wave-1 names.
      expect(names).toContain("list_parameters");
      // The promoted Wave-3b sketch tool is live now, not a roadmap name.
      expect(names).toContain("create_sketch");
      expect(names).toHaveLength(32);
      expect(events.some((event) => event.tool === "execute_python")).toBe(true);
    } finally {
      await harness_.close();
    }
  });

  it("keeps the full live surface visible: 30 add-in tools plus the bridge-owned probes", async () => {
    const harness_ = await harness();
    try {
      const names = (await harness_.client.listTools()).tools.map((tool) => tool.name);
      expect(names).toHaveLength(32);
      expect(names).toEqual(
        expect.arrayContaining([
          // Wave-1: viewport, selection, documentation.
          "capture_viewport",
          "get_viewport",
          "set_viewport",
          "get_active_selection",
          "fetch_api_documentation",
          "fetch_online_documentation",
          "fetch_design_guide",
          // Wave-2: lifecycle, documents, parameters.
          "fusion_status",
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
          // Wave-2 diagnostics.
          "fusion_diagnostics",
          // Wave-3a: feature creation.
          "fillet",
          "chamfer",
          "hole",
          "rectangular_pattern",
          "circular_pattern",
          // Wave-3b: sketch, extrude/revolve, structure, and appearance.
          "create_sketch",
          "extrude",
          "revolve",
          "create_component",
          "create_body",
          "apply_appearance",
          // Bridge-owned; answered locally, never forwarded.
          "fusion_health",
          "list_tool_categories",
        ]),
      );
    } finally {
      await harness_.close();
    }
  });

  it("answers fusion_health locally and never forwards it", async () => {
    const harness_ = await harness();
    try {
      const forwardedBefore = addin.forwardedCalls.length;
      const result: CallToolResult = await harness_.client.callTool({ name: "fusion_health" });

      expect(result.isError).not.toBe(true);
      const report = JSON.parse((result.content[0] as { text: string }).text) as {
        connected: boolean;
        host: string;
        port: number;
        protocol_version: string | null;
      };
      expect(report.connected).toBe(true);
      expect(report.host).toBe("127.0.0.1");
      expect(report.port).toBe(addin.port);
      expect(report.protocol_version).not.toBe(null);
      expect(addin.forwardedCalls.length).toBe(forwardedBefore);
    } finally {
      await harness_.close();
    }
  });

  it("answers list_tool_categories locally and never forwards it", async () => {
    const harness_ = await harness();
    try {
      const forwardedBefore = addin.forwardedCalls.length;
      const result: CallToolResult = await harness_.client.callTool({ name: "list_tool_categories" });

      expect(result.isError).not.toBe(true);
      const report = JSON.parse((result.content[0] as { text: string }).text) as {
        categories: Array<{ name: string; description: string; tools: string[] }>;
        total_tools: number;
      };
      expect(report.total_tools).toBe(32);
      // The closed category set the add-in declares, nothing outside it.
      expect(report.categories.map((category) => category.name)).toEqual([
        "viewport",
        "selection",
        "documents",
        "parameters",
        "documentation",
        "diagnostics",
        "features",
      ]);
      // Every live tool is classified exactly once across the categories.
      const classified = report.categories.flatMap((category) => category.tools);
      expect(classified).toHaveLength(32);
      expect(new Set(classified).size).toBe(32);
      // Retired and BLOCKED_HARD names can never be surfaced.
      expect(classified).not.toContain("apply_material");
      expect(classified).not.toContain("execute_python");
      expect(addin.forwardedCalls.length).toBe(forwardedBefore);
    } finally {
      await harness_.close();
    }
  });

  it("rejects a blocked tool call with an isError result", async () => {
    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "execute_python",
        arguments: { code: "print('pwned')" },
      });

      const body = errorEnvelope(result);
      expect(body.error_kind).toBe("blocked_hard");
      expect(body.message).toContain("execute_python");
      expect(body.hint).toContain("tools/list");
      expect(events.some((event) => event.tool === "execute_python")).toBe(true);
      // The refused arguments must not be echoed back into the error body.
      expect(JSON.stringify(result)).not.toMatch(/print\('pwned'\)/);
    } finally {
      await harness_.close();
    }
  });

  it("rejects a tool the gate does not admit with the not_allowed kind", async () => {
    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "apply_material",
        arguments: { body: "$body_0", appearance: "Steel" },
      });

      const body = errorEnvelope(result);
      expect(body.error_kind).toBe("not_allowed");
      expect(body.message).toContain("apply_material");
      expect(body.message).toContain("tools/list");
    } finally {
      await harness_.close();
    }
  });

  it("forwards a promoted Wave-2 tool instead of refusing it", async () => {
    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "fusion_status",
        arguments: {},
      });
      expect(result.isError).not.toBe(true);
      expect((result.content[0] as { text: string }).text).toBe("called fusion_status");
      expect(addin.forwardedCalls).toContain("fusion_status");
    } finally {
      await harness_.close();
    }
  });

  it("forwards a promoted Wave-3b tool instead of refusing it", async () => {
    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "create_sketch",
        arguments: {
          plane: "xy",
          curves: [
            { kind: "line", start: { x: 0, y: 0, z: 0 }, end: { x: 2, y: 0, z: 0 } },
            { kind: "line", start: { x: 2, y: 0, z: 0 }, end: { x: 2, y: 2, z: 0 } },
            { kind: "line", start: { x: 2, y: 2, z: 0 }, end: { x: 0, y: 2, z: 0 } },
            { kind: "line", start: { x: 0, y: 2, z: 0 }, end: { x: 0, y: 0, z: 0 } },
          ],
        },
      });
      expect(result.isError).not.toBe(true);
      expect((result.content[0] as { text: string }).text).toBe("called create_sketch");
      expect(addin.forwardedCalls).toContain("create_sketch");
    } finally {
      await harness_.close();
    }
  });

  it("accepts a circle curve that omits line-only members", async () => {
    const harness_ = await harness();
    try {
      // The add-in's validator has no oneOf: one flattened curve schema serves all
      // three variants, and only 'kind' is required. The bridge mirrors that shape,
      // so a circle without start/end must pass the gate just as it would upstream.
      const result: CallToolResult = await harness_.client.callTool({
        name: "create_sketch",
        arguments: {
          plane: "xy",
          curves: [{ kind: "circle", center: { x: 1, y: 1, z: 0 }, radius: 1 }],
        },
      });
      expect(result.isError).not.toBe(true);
      expect((result.content[0] as { text: string }).text).toBe("called create_sketch");
    } finally {
      await harness_.close();
    }
  });

  it("reports invalid_arguments for a curve kind the add-in does not serve", async () => {
    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "create_sketch",
        arguments: { plane: "xy", curves: [{ kind: "spline" }] },
      });

      const body = errorEnvelope(result);
      expect(body.error_kind).toBe("invalid_arguments");
      expect(body.message).toContain("create_sketch");
      expect(body.hint).toContain("kind");
      expect(addin.forwardedCalls).not.toContain("create_sketch");
    } finally {
      await harness_.close();
    }
  });

  it("reports invalid_arguments when an unknown argument key slips in", async () => {
    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "close_document",
        // .strict() rejects an unknown key instead of silently stripping it; an
        // object with the right shape still reaches zod, unlike a non-object
        // payload which the SDK refuses client-side before the bridge sees it.
        arguments: { save: false, force_close: true },
      });

      const body = errorEnvelope(result);
      expect(body.error_kind).toBe("invalid_arguments");
      expect(body.message).toContain("close_document");
      expect(body.hint).toContain("force_close");
      expect(addin.forwardedCalls).not.toContain("close_document");
    } finally {
      await harness_.close();
    }
  });

  it("rejects an unknown tool with the not_allowed kind", async () => {
    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "definitely_not_a_tool",
        arguments: {},
      });

      const body = errorEnvelope(result);
      expect(body.error_kind).toBe("not_allowed");
      expect(body.message).toContain("definitely_not_a_tool");
      expect(body.hint).toContain("tools/list");
    } finally {
      await harness_.close();
    }
  });

  it("reports invalid_arguments with the failing field path in the hint", async () => {
    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "new_document",
        // design_type must be parametric or direct; "blueprint" is neither.
        arguments: { name: "Bracket", design_type: "blueprint" },
      });

      const body = errorEnvelope(result);
      expect(body.error_kind).toBe("invalid_arguments");
      expect(body.message).toContain("new_document");
      // The field path, not a stack, is what tells the LLM what to fix.
      expect(body.hint).toContain("design_type");
      expect(body.hint).not.toMatch(/at Object\.|Traceback/);
      expect(addin.forwardedCalls).not.toContain("new_document");
    } finally {
      await harness_.close();
    }
  });

  it("reports invalid_arguments for a nested field path", async () => {
    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "set_viewport",
        arguments: { camera: { eye: "not-a-point" } },
      });

      const body = errorEnvelope(result);
      expect(body.error_kind).toBe("invalid_arguments");
      expect(body.hint).toContain("camera.eye");
      expect(addin.forwardedCalls).not.toContain("set_viewport");
    } finally {
      await harness_.close();
    }
  });

  it("forwards an allowed call and returns the tool result", async () => {
    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "capture_viewport",
        arguments: {},
      });
      expect(result.isError).not.toBe(true);
      expect((result.content[0] as { text: string }).text).toBe("called capture_viewport");
      expect(addin.forwardedCalls).toContain("capture_viewport");
    } finally {
      await harness_.close();
    }
  });

  it("maps a JSON-RPC tool error onto tier (b)", async () => {
    const port = addin.port;
    await addin.close();
    addin = new FakeAddin({ mode: "json", port, failToolCalls: true });
    await addin.start();
    resetResolvedHost();

    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "capture_viewport",
        arguments: {},
      });

      const body = errorEnvelope(result);
      expect(body.error_kind).toBe("tool_failed");
      expect(body.message).toContain("failed (code -32603)");
    } finally {
      await harness_.close();
    }
  });

  it("never echoes the add-in's exception message or traceback", async () => {
    // lib/mcp_server.py's dispatch catch-all builds `message` from str(exc) and
    // puts the traceback in `data`. Neither may reach the LLM.
    const leaky = {
      code: -32603,
      message: "Internal error: ValueError('boom')",
      data: ["Traceback (most recent call last):", '  File "tools.py", line 42, in handle', "ValueError: boom"].join(
        "\n",
      ),
    };
    const port = addin.port;
    await addin.close();
    addin = new FakeAddin({ mode: "json", port, leakyToolError: leaky });
    await addin.start();
    resetResolvedHost();

    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "capture_viewport",
        arguments: {},
      });

      const body = errorEnvelope(result);
      expect(body.error_kind).toBe("tool_failed");
      expect(body.message).toContain("code -32603");
      expect(body.hint.length).toBeGreaterThan(0);

      const whole = JSON.stringify(result);
      expect(whole).not.toMatch(/Traceback/);
      expect(whole).not.toMatch(/ValueError/);
      expect(whole).not.toMatch(/Internal error:/);
      expect(whole).not.toMatch(/tools\.py/);
    } finally {
      await harness_.close();
    }
  });

  it("surfaces an add-in structured error envelope unchanged", async () => {
    // The add-in's own envelope (error_kind/message/hint) is its contract with
    // the LLM; the bridge passes it through, never re-wrapping or rewording it.
    const addinEnvelope = {
      error_kind: "no_active_document",
      message: "No active Fusion document is open for this operation.",
      hint: "Open or create a Fusion design document first, then retry the call.",
    };
    const port = addin.port;
    await addin.close();
    addin = new FakeAddin({ mode: "json", port, structuredToolError: addinEnvelope });
    await addin.start();
    resetResolvedHost();

    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "export_document",
        arguments: { format: "stl", path: "/tmp/out.stl" },
      });

      expect(result.isError).toBe(true);
      expect((result.content[0] as { text: string }).text).toBe(JSON.stringify(addinEnvelope, null, 2));
    } finally {
      await harness_.close();
    }
  });

  it("maps an unreachable add-in onto tier (c) with actionable text", async () => {
    const port = addin.port;
    await addin.close();
    resetResolvedHost();

    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "capture_viewport",
        arguments: {},
      });

      const body = errorEnvelope(result);
      expect(body.error_kind).toBe("addin_unreachable");
      expect(body.message).toContain(`Fusion 360 is not reachable at 127.0.0.1:${port}`);
      expect(body.hint).toContain("AutodeskFusionMCP");
      expect(body.hint).toContain("FUSION_MCP_HOST");
    } finally {
      await harness_.close();
    }
  });

  it("maps an HTTP 403 add-in onto addin_forbidden, not an outage", async () => {
    const port = addin.port;
    await addin.close();
    // forceToolCallStatus, not forceStatus: a GLOBAL 403 refuses the ping probe
    // too, and the state machine legitimately collapses that to unreachable
    // (probe failure ⇒ tier (c)). Refusing only tools/call is the shape that
    // reaches the forbidden tier, so connection.ts needs no change.
    addin = new FakeAddin({ mode: "json", port, forceToolCallStatus: 403 });
    await addin.start();
    resetResolvedHost();

    const harness_ = await harness();
    try {
      const result: CallToolResult = await harness_.client.callTool({
        name: "capture_viewport",
        arguments: {},
      });

      const body = errorEnvelope(result);
      expect(body.error_kind).toBe("addin_forbidden");
      expect(body.message).toContain(`rejected the request (HTTP 403)`);
      expect(body.message).toContain("Origin header, not the host");
    } finally {
      await harness_.close();
    }
  });

  it("still lists the bridge-owned probes when the add-in is down", async () => {
    await addin.close();
    resetResolvedHost();

    const harness_ = await harness();
    try {
      const names = (await harness_.client.listTools()).tools.map((tool) => tool.name);
      // Both bridge-owned helpers stay advertised when the add-in is
      // unreachable; nothing proxied survives the failed tools/list.
      expect(names).toEqual(["fusion_health", "list_tool_categories"]);
    } finally {
      await harness_.close();
    }
  });

  it("offers the same tools over an SSE-framed add-in", async () => {
    const port = addin.port;
    await addin.close();
    addin = new FakeAddin({ mode: "sse", port });
    await addin.start();
    resetResolvedHost();

    const harness_ = await harness();
    try {
      const names = (await harness_.client.listTools()).tools.map((tool) => tool.name);
      expect(names).toContain("capture_viewport");
      expect(names).not.toContain("execute_python");
    } finally {
      await harness_.close();
    }
  });
});

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
