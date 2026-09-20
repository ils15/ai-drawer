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
 * zod argument schemas for the whole live surface. These mirror the add-in's
 * tool_surface.py one-to-one: every property, required flag, enum, bound and
 * description is transcribed from it, and the cross-package drift guard in
 * tests/drift-guard.test.ts fails the build if the two ever diverge.
 *
 * Conventions, imposed by the add-in's own schema vocabulary
 * (OwnedSchemaTests in the add-in test suite):
 *  - plain z.string(), never .min(1). Empty-string rejection happens in the
 *    add-in handler, which reports the real Fusion error.
 *  - .strict() on every object the add-in declares additionalProperties:false
 *    for; z.object() would silently STRIP unknown keys instead of rejecting.
 *  - descriptions attached with .describe(), byte-exact from tool_surface.py.
 *
 * The bridge forwards the RAW arguments, not zod's parsed output, so these
 * schemas are a gate: they reject what the add-in would reject, without
 * becoming a second source of truth for defaults.
 */
const STANDARD_VIEWS = [
  "front",
  "back",
  "left",
  "right",
  "top",
  "bottom",
  "isometric",
  "iso_top_left",
  "iso_top_right",
  "iso_bottom_left",
  "iso_bottom_right",
] as const;
const PROJECTIONS = ["orthographic", "perspective", "perspective_with_ortho_faces"] as const;
const DESIGN_TYPES = ["parametric", "direct"] as const;
const EXPORT_FORMATS = ["step", "stl", "f3d", "iges", "obj", "pdf"] as const;
const STL_DENSITY = ["low", "medium", "high"] as const;
const STL_UNITS = ["mm", "cm", "in", "m"] as const;

/** xyz point in centimeters; shared by the get_viewport/set_viewport camera. */
const pointSchema = z.strictObject({
  x: z.number().min(-1e12).max(1e12),
  y: z.number().min(-1e12).max(1e12),
  z: z.number().min(-1e12).max(1e12),
});

export const TOOL_ARGS: Readonly<Record<string, z.ZodType>> = {
  capture_viewport: z
    .object({
      width: z
        .number()
        .int()
        .min(0)
        .max(8192)
        .optional()
        .describe("Rendered image width in pixels (default: 800; 0 uses viewport width)"),
      height: z
        .number()
        .int()
        .min(0)
        .max(8192)
        .optional()
        .describe("Rendered image height in pixels (default: 600; 0 uses viewport height)"),
      view: z
        .enum(STANDARD_VIEWS)
        .optional()
        .describe("Temporary ViewCube-relative standard view; omit to keep current view."),
      fit: z.boolean().optional().describe("Temporarily fit all graphics before capture (default: false)."),
      background: z.string().optional().describe("viewport (default), transparent, or a solid #RRGGBB color."),
      anti_aliasing: z.boolean().optional().describe("Smooth rendered edges (default: true)."),
      crop: z
        .strictObject({
          x: z.number().int().min(0).max(8192),
          y: z.number().int().min(0).max(8192),
          width: z.number().int().min(1).max(8192),
          height: z.number().int().min(1).max(8192),
        })
        .optional()
        .describe("Rectangle inside the rendered image; output dimensions equal crop width/height."),
    })
    .describe(
      "Capture the active Fusion viewport as a PNG. Optional view and fit are temporary: " +
        "the original camera is restored even on failure. Background can be viewport, " +
        "transparent, or #RRGGBB. Crop uses pixels in the rendered image, origin top-left. " +
        "Returns only the cropped region when crop is provided; limit 16 megapixels.",
    ),
  get_viewport: z
    .object({})
    .describe(
      "Read active viewport pixel dimensions and camera eye, target, up_vector, projection, " +
        "and extents or perspective_angle. Lengths are cm and angles degrees. " +
        "Pass the returned camera object to set_viewport to restore it. All clients share this viewport.",
    ),
  set_viewport: z
    .strictObject({
      camera: z
        .strictObject({
          eye: pointSchema,
          target: pointSchema,
          up_vector: pointSchema,
          projection: z.enum(PROJECTIONS),
          extents: z
            .strictObject({
              width: z.number().min(1e-9).max(1e12),
              height: z.number().min(1e-9).max(1e12),
            })
            .optional()
            .describe("Required for orthographic cameras only, in cm."),
          perspective_angle: z
            .number()
            .min(0.01)
            .max(179)
            .optional()
            .describe("Required for perspective cameras only; angle in degrees."),
        })
        .optional()
        .describe(
          "Camera snapshot from get_viewport. Coordinates/extents in cm; " +
            "perspective_angle in degrees. Use alone to restore a camera.",
        ),
      view: z.enum(STANDARD_VIEWS).optional(),
      projection: z.enum(PROJECTIONS).optional(),
      fit: z.boolean().optional().describe("Fit all graphics (default: false)."),
      orbit: z
        .strictObject({
          yaw: z.number().min(-360).max(360).optional(),
          pitch: z.number().min(-360).max(360).optional(),
          roll: z.number().min(-360).max(360).optional(),
        })
        .optional(),
      pan: z
        .strictObject({
          x: z.number().min(-1e9).max(1e9).optional(),
          y: z.number().min(-1e9).max(1e9).optional(),
        })
        .optional(),
      zoom: z.number().min(0.01).max(100).optional(),
      description: z.string().optional(),
    })
    .describe(
      "Control the active Fusion camera. Changes apply in order: projection/view, fit, orbit, pan, zoom. " +
        "Standard views follow the user's ViewCube orientation. Orbit angles use right-hand rotation: " +
        "yaw about camera up, pitch about camera right, roll about the viewing direction. " +
        "Pan translates the camera along screen right/up in cm. Zoom >1 zooms in; <1 zooms out. " +
        "Alternatively pass a complete camera snapshot alone. Returns actual camera state. " +
        "This changes the shared viewport for all clients, without modifying model geometry.",
    ),
  get_active_selection: z
    .object({})
    .describe(
      "Get the objects currently selected by the user in the Fusion 360 viewport. " +
        "Returns detailed info per item (type, name, entityToken, parent component, " +
        "and type-specific properties like area, volume, material).",
    ),
  fetch_api_documentation: z
    .object({
      search_term: z.string().describe("Search term (e.g. 'BRepBody', 'sketches', 'adsk.fusion.Sketch.add')"),
      category: z.string().optional().describe("Search category: class_name, member_name, description, or all"),
      max_results: z.number().int().optional().describe("Maximum number of results (default: 3)"),
    })
    .describe(
      "Search live Fusion API metadata through runtime introspection. " +
        "Returns scored results with class overviews, properties, " +
        "and function signatures.",
    ),
  fetch_online_documentation: z
    .object({
      class_name: z.string().describe("API class name (e.g. 'BRepBody', 'Sketch')"),
      member_name: z.string().optional().describe("Optional member name (e.g. 'add', 'name')"),
    })
    .describe("Fetch Autodesk cloudhelp documentation for a specific Fusion API class or member."),
  fetch_design_guide: z
    .object({})
    .describe(
      "Read the bundled Fusion design guide with workflow guidance, " +
        "API patterns, naming rules, and modeling habits.",
    ),
  fusion_status: z
    .object({})
    .strict()
    .describe(
      "Report the state of the running Fusion: version, active document name, modified flag, " +
        "design units, design type (parametric or direct), active workspace, timeline feature count, " +
        "and how long this add-in has been running. Works with no document open; document fields " +
        "are then null. Use this first to learn what you are working with.",
    ),
  list_documents: z
    .object({})
    .strict()
    .describe(
      "List every document currently open in Fusion, with name, active flag, modified flag, " +
        "design type, and saved path (null when never saved). Use fusion_status for the active " +
        "document's deeper detail.",
    ),
  new_document: z
    .strictObject({
      name: z.string().describe("Name for the new document."),
      design_type: z
        .enum(DESIGN_TYPES)
        .optional()
        .describe("Parametric (default) keeps a timeline; direct is history-free."),
    })
    .describe(
      "Create and activate a new Fusion design document with the given name. The optional " +
        "design_type selects parametric (timeline history, default) or direct (history-free) " +
        "modeling; switching to direct removes the timeline. Returns the document name and " +
        "the design type that was applied.",
    ),
  open_document: z
    .strictObject({
      path: z.string().describe("Path of the file to open."),
    })
    .describe(
      "Open a previously saved Fusion file (.f3d, .f3z, .step, .iges, .smt, .sat, .dwg, ...) " +
        "by path and activate it. Returns the document name and its modified flag. The path is " +
        "passed to Fusion's open; local file paths are supported.",
    ),
  save_document: z
    .strictObject({
      path: z.string().optional().describe("Save-as target; omit to save the existing file in place."),
    })
    .describe(
      "Save the active document. Omit path to save in place (fails with a clear error if the " +
        "document has never been saved). Provide path to save-as, which also works for a never-saved " +
        "document; the path's folder is used as the save location and its file name as the document " +
        "name. Returns the resulting saved path.",
    ),
  export_document: z
    .strictObject({
      format: z.enum(EXPORT_FORMATS).describe("Export format."),
      path: z.string().describe("Output file path."),
      stl_density: z.enum(STL_DENSITY).optional().describe("STL mesh refinement (default: medium)."),
      stl_units: z
        .enum(STL_UNITS)
        .optional()
        .describe("Units the unitless STL numbers represent (default: design units)."),
    })
    .describe(
      "Export the active design to step, stl, f3d, iges, obj, or pdf, writing to the given path " +
        "and reporting the file size in bytes. Requires an active design; returns a clear error " +
        "otherwise. For stl, stl_density maps to mesh refinement (low/medium/high, default medium) " +
        "and stl_units selects the units the unitless STL numbers represent (default: the design's " +
        "units). Not every Fusion build can emit every format; unsupported combinations are " +
        "reported rather than silently ignored.",
    ),
  close_document: z
    .strictObject({
      document_name: z.string().optional().describe("Document to close; omit for the active one."),
      save: z.boolean().optional().describe("Save in place before closing (default: false)."),
    })
    .describe(
      "Close the active document, or the one named by document_name. Set save true to persist " +
        "changes first (the document must already have a save location; otherwise save it with " +
        "save_document first). Unsaved changes are discarded when save is false or omitted. " +
        "Returns closed: true/false.",
    ),
  get_document_info: z
    .object({})
    .strict()
    .describe(
      "Report the active document's name, saved path, default length units, design type, " +
        "modified flag, and version. Returns a clear error when no document is open.",
    ),
  list_parameters: z
    .object({})
    .strict()
    .describe(
      "List every user and model parameter in the active design. Each entry carries name, " +
        'expression (Fusion expression string, e.g. "25 mm" or "width / 2"), unit, value ' +
        "(the evaluated number; lengths are in the parameter's internal centimeter units), " +
        "parameter_type (user or model), and driven (true when the model computes the value).",
    ),
  add_parameter: z
    .strictObject({
      name: z.string().describe("Parameter name; must be unique."),
      expression: z.string().describe('Fusion expression, e.g. "3 mm" or "width/2".'),
      unit: z.string().optional().describe("Parameter unit label (default: mm)."),
    })
    .describe(
      "Add a user parameter to the active design. The expression is a Fusion expression string " +
        '("3 mm", "width/2", "45 deg") and is consumed by the expression engine, so units ' +
        "inside it are honored. The optional unit string (default mm) labels the parameter. " +
        "Fails with a clear error on a duplicate name or an invalid expression.",
    ),
  modify_parameter: z
    .strictObject({
      name: z.string().describe("Existing parameter name."),
      expression: z.string().describe('New Fusion expression, e.g. "40 mm" or "height * 2".'),
    })
    .describe(
      "Change an existing parameter's expression and recompute the model in one pass — the " +
        "cheapest edit path. Returns the new expression, its evaluated value, whether a recompute " +
        "ran, and recomputed_feature_count (features that re-evaluated; null when the running " +
        "Fusion cannot report it). Use this to drive dimensions instead of recreating geometry.",
    ),
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
