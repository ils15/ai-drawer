/**
 * MCP server: the stdio face OpenCode talks to.
 *
 * Per-request pipeline, in strict order:
 *   1. Route bridge-owned tools (fusion_health) locally. Never forwarded.
 *   2. Gate every call through the allowlist BEFORE inspecting arguments.
 *   3. Validate arguments with zod before anything crosses the wire.
 *   4. Forward to the add-in through the connection state machine.
 *   5. Map the upstream outcome onto exactly one of the three error tiers.
 *
 * tools/list is proxied from the add-in and then filtered, so the LLM only
 * ever sees the curated surface even if the add-in advertises more.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  type CallToolRequest,
  CallToolRequestSchema,
  CallToolResultSchema,
  ListToolsRequestSchema,
  ListToolsResultSchema,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";
import { denyMessage, filterToolList, gateToolCall, HEALTH_TOOL } from "./allowlist.js";
import { resolveHost } from "./config.js";
import type { HealthReport } from "./connection.js";
import { ConnectionMonitor } from "./connection.js";
import {
  bridgeBugFailure,
  forbiddenFailure,
  type ToolResult,
  toolFailure,
  toolJson,
  unreachableFailure,
} from "./errors.js";
import { asJsonRpcError, asJsonRpcSuccess } from "./json-rpc.js";
import { sendUpstream, type UpstreamFailureKind } from "./upstream-client.js";

const SERVER_NAME = "ai-drawer-mcp";
const SERVER_VERSION = "0.1.0";
const CALL_TIMEOUT_MS = 60_000;
const LIST_TIMEOUT_MS = 15_000;

/**
 * zod argument schemas for the Wave-1 tools. These enforce only what the
 * bridge forwards; the add-in validates against its own contracts too.
 * Enabling a Wave-3 tool means adding one entry here AND one name to ALLOWED.
 */
const TOOL_ARGS: Readonly<Record<string, z.ZodType>> = {
  capture_viewport: z.object({
    width: z.number().int().positive().optional(),
    height: z.number().int().positive().optional(),
  }),
  get_viewport: z.object({}).optional(),
  set_viewport: z.object({ width: z.number().int().positive(), height: z.number().int().positive() }),
  get_active_selection: z.object({}).optional(),
  fetch_api_documentation: z.object({ query: z.string().optional() }),
  fetch_online_documentation: z.object({ query: z.string().optional() }),
  fetch_design_guide: z.object({ topic: z.string().optional() }),
};

export interface BridgeServer {
  readonly server: Server;
  readonly monitor: ConnectionMonitor;
  close(): Promise<void>;
}

/** Builds the server. `initialize` is handled by the SDK; this wires the handlers. */
export async function createBridgeServer(): Promise<BridgeServer> {
  const endpoint = await resolveHost();
  const monitor = new ConnectionMonitor(endpoint);

  const server = new Server(
    { name: SERVER_NAME, version: SERVER_VERSION },
    {
      capabilities: { tools: {} },
      instructions: [
        "Fusion 360 bridge. Tools execute inside Autodesk Fusion via a local add-in.",
        "Call fusion_health first to confirm Fusion is running and the add-in is started.",
        "Only the tools returned by tools/list are callable; other names are refused.",
      ].join(" "),
    },
  );

  server.setRequestHandler(ListToolsRequestSchema, () => handleListTools(monitor));
  server.setRequestHandler(CallToolRequestSchema, (request) => handleCallTool(request, monitor));

  // One upstream initialize at startup, best-effort. A closed Fusion or an
  // unstarted add-in is not fatal: tools/list and tools/call degrade to the
  // tier-(c) actionable guidance instead of failing the boot.
  void monitor.initialize().catch((error: unknown) => {
    console.error(`[ai-drawer-mcp] upstream initialize failed: ${String(error)}`);
  });

  return { server, monitor, close: async () => server.close() };
}

/** Boots the bridge on stdio. Used by bin.ts. */
export async function runStdio(): Promise<BridgeServer> {
  const bridge = await createBridgeServer();
  const transport = new StdioServerTransport();
  await bridge.server.connect(transport);
  return bridge;
}

/**
 * tools/list: proxy the add-in's list, then filter it through the allowlist.
 * When the add-in is unreachable the bridge still reports its own
 * fusion_health tool, so the LLM can diagnose the outage instead of seeing
 * an empty list with no explanation.
 */
async function handleListTools(monitor: ConnectionMonitor): Promise<{ tools: Tool[] }> {
  const { host, port } = monitor.endpoint;
  const result = await sendUpstream(
    host,
    port,
    { jsonrpc: "2.0", id: nextRequestId(), method: "tools/list" },
    LIST_TIMEOUT_MS,
  );

  if (!result.ok) return { tools: [healthTool()] };

  const success = asJsonRpcSuccess(result.message);
  if (success === null) {
    // A method-not-found error means the add-in predates tools/list: nothing
    // to proxy. Anything else is a protocol problem; report health only.
    const error = asJsonRpcError(result.message);
    return { tools: error !== null && error.error.code === -32601 ? [] : [healthTool()] };
  }

  const parsed = ListToolsResultSchema.safeParse(success.result);
  if (!parsed.success) return { tools: [healthTool()] };

  const advertised: readonly Tool[] = parsed.data.tools;
  const byName = new Map<string, Tool>(advertised.map((tool) => [tool.name, tool]));

  const tools: Tool[] = [];
  for (const name of filterToolList(advertised.map((tool) => tool.name))) {
    const tool = byName.get(name);
    if (tool !== undefined) tools.push(tool);
  }
  if (!tools.some((tool) => tool.name === HEALTH_TOOL)) tools.push(healthTool());

  return { tools };
}

/** fusion_health is bridge-owned: answered locally, never forwarded. */
function healthTool(): Tool {
  return {
    name: HEALTH_TOOL,
    description:
      "Reports whether the Fusion 360 add-in is reachable: connection state, endpoint in use, latency, protocol version and last error. Bridge-owned; available even when Fusion is closed.",
    inputSchema: { type: "object", properties: {} },
  };
}

/** tools/call: gate → validate → forward → map to an error tier. */
async function handleCallTool(request: CallToolRequest, monitor: ConnectionMonitor): Promise<ToolResult> {
  const name: string = request.params.name;
  const args: unknown = request.params.arguments;

  // 1. Bridge-owned tool, answered locally and never forwarded.
  if (name === HEALTH_TOOL) {
    const report: HealthReport = await monitor.health();
    return toolJson(report);
  }

  // 2. Security gate, before any argument is inspected.
  const gate = gateToolCall(name);
  if (!gate.allowed) {
    return toolFailure(`Tool '${name}' is not available.`, denyMessage(name, gate.reason ?? "not-allowed"));
  }

  // 3. Validate arguments with zod before they cross the wire.
  const schema = TOOL_ARGS[name];
  if (schema !== undefined && args !== undefined) {
    const validated = schema.safeParse(args);
    if (!validated.success) {
      return toolFailure(
        `Invalid arguments for '${name}'.`,
        validated.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("\n"),
      );
    }
  }

  // 4. Forward through the state machine.
  const outcome = await monitor.send({ method: "tools/call", params: { name, arguments: args } }, CALL_TIMEOUT_MS);
  if (outcome.ok) return mapToolResult(outcome.message, name);

  // 5. Map the failure onto the tier that matches where it happened.
  return mapFailure(outcome.kind, outcome.detail, name, monitor);
}

/** Converts an upstream reply into a tools/call result, honoring error tiers. */
function mapToolResult(message: unknown, name: string): ToolResult {
  const error = asJsonRpcError(message);
  if (error !== null) {
    // Tier (b): the add-in executed the tool and the tool failed.
    return toolFailure(`Tool '${name}' failed (code ${error.error.code}).`, error.error.message);
  }

  const success = asJsonRpcSuccess(message);
  if (success === null) return toolFailure(`Tool '${name}' returned an unreadable reply.`);

  const parsed = CallToolResultSchema.safeParse(success.result);
  if (!parsed.success) {
    return toolFailure(
      `Tool '${name}' returned a malformed result.`,
      "reply did not match the MCP CallToolResult schema",
    );
  }

  return parsed.data;
}

/** Tier mapping: where the failure happened decides what the LLM is told. */
function mapFailure(kind: UpstreamFailureKind, detail: string, name: string, monitor: ConnectionMonitor): ToolResult {
  const { host, port } = monitor.endpoint;

  switch (kind) {
    case "unreachable":
      // Tier (c): actionable text naming the exact endpoint attempted.
      return unreachableFailure(host, port, detail);
    case "timeout":
      return unreachableFailure(host, port, `Timed out after ${CALL_TIMEOUT_MS}ms. ${detail}`);
    case "forbidden":
      // Reachable but refused: an origin/identity problem, not an outage.
      return forbiddenFailure(host, port, detail);
    case "bridge-bug":
      return bridgeBugFailure(406);
    default:
      return toolFailure(`Tool '${name}' failed with a protocol error.`, detail);
  }
}

let requestCounter = 0;

/** Monotonic JSON-RPC ids for requests the bridge originates. */
function nextRequestId(): number {
  requestCounter = (requestCounter % 0xffff) + 1;
  return requestCounter;
}
