/**
 * MCP server: the stdio face OpenCode talks to.
 *
 * Per-request pipeline, in strict order:
 *   1. Route bridge-owned tools (fusion_health, list_tool_categories) locally.
 *      Never forwarded.
 *   2. Gate every call through the allowlist BEFORE inspecting arguments.
 *   3. Validate arguments with zod before anything crosses the wire.
 *   4. Forward to the add-in through the connection state machine.
 *   5. Map the upstream outcome onto a structured error envelope, or pass the
 *      add-in's own result through unchanged.
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
import { CATEGORY_TOOL, filterToolList, gateToolCall, HEALTH_TOOL } from "./allowlist.js";
import { categoryTool, listToolCategories } from "./categories.js";
import { resolveHost } from "./config.js";
import type { HealthReport } from "./connection.js";
import { ConnectionMonitor } from "./connection.js";
import {
  bridgeBugFailure,
  forbiddenFailure,
  gateFailure,
  invalidArguments,
  protocolFailure,
  type ToolResult,
  timeoutFailure,
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
const pointSchema = z
  .strictObject({
    x: z.number().min(-1e12).max(1e12).describe("X component in centimeters."),
    y: z.number().min(-1e12).max(1e12).describe("Y component in centimeters."),
    z: z.number().min(-1e12).max(1e12).describe("Z component in centimeters."),
  })
  .describe("A 3D position or direction vector; x, y, and z are in centimeters.");

/**
 * One sketch curve, discriminated by 'kind'. The add-in's owned validator has no
 * `oneOf` branch, so the three variants share a single object schema there too:
 * only 'kind' is required, and the handler enforces which members each variant
 * needs (a line needs start and end, a circle center and radius, an arc center,
 * start, and sweep). The bridge mirrors that flattened shape exactly — no zod
 * discriminatedUnion — and forwards raw arguments for the add-in to validate per
 * variant, so the gate never rejects a curve the add-in would accept.
 */
const curveSchema = z
  .strictObject({
    kind: z.enum(["line", "circle", "arc"]).describe("Which curve this is, and which members are required."),
    start: pointSchema.optional(),
    end: pointSchema.optional(),
    center: pointSchema.optional(),
    radius: z
      .number()
      .min(1e-9)
      .max(1e12)
      .optional()
      .describe("Circle radius in centimetres.")
      .meta({ examples: [1] }),
    sweep: z
      .number()
      .min(-360)
      .max(360)
      .optional()
      .describe("Arc sweep in degrees; positive is counter-clockwise.")
      .meta({ examples: [90] }),
  })
  .describe(
    "One sketch curve: a line, a circle, or an arc, told apart by 'kind'. Points are in centimetres; " +
      "a line needs start and end, a circle needs center and radius, and an arc needs center, start, and sweep degrees.",
  );

/**
 * Primitive body dimensions, flattened the same way curveSchema is: the add-in's
 * validator has no `oneOf`, so no member is required here and the handler
 * enforces which ones each shape needs (box length/width/height, cylinder
 * radius/height, sphere radius).
 */
const dimensionsSchema = z
  .strictObject({
    length: z
      .number()
      .min(1e-9)
      .max(1e12)
      .optional()
      .describe("Box length along the x axis in centimetres.")
      .meta({ examples: [2] }),
    width: z
      .number()
      .min(1e-9)
      .max(1e12)
      .optional()
      .describe("Box width along the y axis in centimetres.")
      .meta({ examples: [2] }),
    height: z
      .number()
      .min(1e-9)
      .max(1e12)
      .optional()
      .describe("Box or cylinder height along the z axis in centimetres.")
      .meta({ examples: [3] }),
    radius: z
      .number()
      .min(1e-9)
      .max(1e12)
      .optional()
      .describe("Cylinder or sphere radius in centimetres.")
      .meta({ examples: [1] }),
  })
  .describe(
    "Body dimensions in centimetres; which members are required depends on the shape: box needs length, " +
      "width, and height; cylinder needs radius and height; sphere needs radius alone.",
  );

export const TOOL_ARGS: Readonly<Record<string, z.ZodType>> = {
  capture_viewport: z
    .object({
      width: z
        .number()
        .int()
        .min(0)
        .max(8192)
        .optional()
        .describe("Rendered image width in pixels (default: 800; 0 uses viewport width)")
        .meta({ examples: [800, 1920] }),
      height: z
        .number()
        .int()
        .min(0)
        .max(8192)
        .optional()
        .describe("Rendered image height in pixels (default: 600; 0 uses viewport height)")
        .meta({ examples: [600, 1080] }),
      view: z
        .enum(STANDARD_VIEWS)
        .optional()
        .describe("Temporary ViewCube-relative standard view; omit to keep current view.")
        .meta({ examples: ["isometric", "front"] }),
      fit: z.boolean().optional().describe("Temporarily fit all graphics before capture (default: false)."),
      background: z
        .string()
        .optional()
        .describe("viewport (default), transparent, or a solid #RRGGBB color.")
        .meta({ examples: ["viewport", "transparent", "#FFFFFF"] }),
      anti_aliasing: z.boolean().optional().describe("Smooth rendered edges (default: true)."),
      crop: z
        .strictObject({
          x: z
            .number()
            .int()
            .min(0)
            .max(8192)
            .describe("Left edge of the crop region, in pixels from the image's left side."),
          y: z
            .number()
            .int()
            .min(0)
            .max(8192)
            .describe("Top edge of the crop region, in pixels from the image's top side."),
          width: z.number().int().min(1).max(8192).describe("Crop region width in pixels."),
          height: z.number().int().min(1).max(8192).describe("Crop region height in pixels."),
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
          projection: z
            .enum(PROJECTIONS)
            .describe("Camera projection; orthographic uses extents, perspective uses perspective_angle."),
          extents: z
            .strictObject({
              width: z.number().min(1e-9).max(1e12).describe("View volume width in centimeters."),
              height: z.number().min(1e-9).max(1e12).describe("View volume height in centimeters."),
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
      view: z
        .enum(STANDARD_VIEWS)
        .optional()
        .describe("Standard ViewCube orientation to apply.")
        .meta({ examples: ["front", "iso_top_right"] }),
      projection: z
        .enum(PROJECTIONS)
        .optional()
        .describe("Camera projection; orthographic uses extents, perspective uses perspective_angle."),
      fit: z.boolean().optional().describe("Fit all graphics (default: false)."),
      orbit: z
        .strictObject({
          yaw: z
            .number()
            .min(-360)
            .max(360)
            .optional()
            .describe("Rotation about the camera's up vector, in degrees.")
            .meta({ examples: [30] }),
          pitch: z
            .number()
            .min(-360)
            .max(360)
            .optional()
            .describe("Rotation about the camera's right vector, in degrees.")
            .meta({ examples: [-15] }),
          roll: z.number().min(-360).max(360).optional().describe("Rotation about the viewing direction, in degrees."),
        })
        .optional()
        .describe("Right-handed rotation angles in degrees about the camera axes."),
      pan: z
        .strictObject({
          x: z
            .number()
            .min(-1e9)
            .max(1e9)
            .optional()
            .describe("Displacement along screen right, in centimeters.")
            .meta({ examples: [5] }),
          y: z
            .number()
            .min(-1e9)
            .max(1e9)
            .optional()
            .describe("Displacement along screen up, in centimeters.")
            .meta({ examples: [2.5] }),
        })
        .optional()
        .describe("Camera translation along screen right and up, in centimeters."),
      zoom: z
        .number()
        .min(0.01)
        .max(100)
        .optional()
        .describe("Dimensionless zoom factor; a ratio where 1 is the current scale.")
        .meta({ examples: [2] }),
      description: z
        .string()
        .optional()
        .describe("Optional caller note recorded with the view change; it is not rendered."),
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
      search_term: z
        .string()
        .describe("Search term (e.g. 'BRepBody', 'sketches', 'adsk.fusion.Sketch.add')")
        .meta({ examples: ["BRepBody", "sketches"] }),
      category: z
        .string()
        .optional()
        .describe("Search category: class_name, member_name, description, or all")
        .meta({ examples: ["class_name", "all"] }),
      max_results: z
        .number()
        .int()
        .optional()
        .describe("Maximum number of results to return (default: 3)")
        .meta({ examples: [5] }),
    })
    .describe(
      "Search live Fusion API metadata through runtime introspection. " +
        "Returns scored results with class overviews, properties, " +
        "and function signatures.",
    ),
  fetch_online_documentation: z
    .object({
      class_name: z
        .string()
        .describe("API class name (e.g. 'BRepBody', 'Sketch')")
        .meta({ examples: ["BRepBody", "Sketch"] }),
      member_name: z
        .string()
        .optional()
        .describe("Optional member name (e.g. 'add', 'name')")
        .meta({ examples: ["add"] }),
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
      name: z
        .string()
        .describe("Name for the new document.")
        .meta({ examples: ["Bracket"] }),
      design_type: z
        .enum(DESIGN_TYPES)
        .optional()
        .describe("Parametric (default) keeps a timeline; direct is history-free.")
        .meta({ examples: ["parametric"] }),
    })
    .describe(
      "Create and activate a new Fusion design document with the given name. The optional " +
        "design_type selects parametric (timeline history, default) or direct (history-free) " +
        "modeling; switching to direct removes the timeline. Returns the document name and " +
        "the design type that was applied.",
    ),
  open_document: z
    .strictObject({
      path: z
        .string()
        .describe("Path of the file to open.")
        .meta({ examples: ["/home/user/designs/bracket.f3d"] }),
    })
    .describe(
      "Open a previously saved Fusion file (.f3d, .f3z, .step, .iges, .smt, .sat, .dwg, ...) " +
        "by path and activate it. Returns the document name and its modified flag. The path is " +
        "passed to Fusion's open; local file paths are supported.",
    ),
  save_document: z
    .strictObject({
      path: z
        .string()
        .optional()
        .describe("Save-as target; omit to save the existing file in place.")
        .meta({ examples: ["/home/user/designs/bracket-v2.f3d"] }),
    })
    .describe(
      "Save the active document. Omit path to save in place (fails with a clear error if the " +
        "document has never been saved). Provide path to save-as, which also works for a never-saved " +
        "document; the path's folder is used as the save location and its file name as the document " +
        "name. Returns the resulting saved path.",
    ),
  export_document: z
    .strictObject({
      format: z
        .enum(EXPORT_FORMATS)
        .describe("Export format.")
        .meta({ examples: ["stl"] }),
      path: z
        .string()
        .describe("Output file path.")
        .meta({ examples: ["/home/user/exports/bracket.stl"] }),
      stl_density: z
        .enum(STL_DENSITY)
        .optional()
        .describe("STL mesh refinement (default: medium).")
        .meta({ examples: ["high"] }),
      stl_units: z
        .enum(STL_UNITS)
        .optional()
        .describe("Units the unitless STL numbers represent (default: design units).")
        .meta({ examples: ["mm"] }),
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
      document_name: z
        .string()
        .optional()
        .describe("Document to close; omit for the active one.")
        .meta({ examples: ["bracket"] }),
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
      name: z
        .string()
        .describe("Parameter name; must be unique.")
        .meta({ examples: ["width"] }),
      expression: z
        .string()
        .describe('Fusion expression, e.g. "3 mm" or "width/2".')
        .meta({ examples: ["3 mm", "width / 2"] }),
      unit: z
        .string()
        .optional()
        .describe("Parameter unit label (default: mm).")
        .meta({ examples: ["mm", "deg"] }),
    })
    .describe(
      "Add a user parameter to the active design. The expression is a Fusion expression string " +
        '("3 mm", "width/2", "45 deg") and is consumed by the expression engine, so units ' +
        "inside it are honored. The optional unit string (default mm) labels the parameter. " +
        "Fails with a clear error on a duplicate name or an invalid expression.",
    ),
  modify_parameter: z
    .strictObject({
      name: z
        .string()
        .describe("Existing parameter name.")
        .meta({ examples: ["width"] }),
      expression: z
        .string()
        .describe('New Fusion expression, e.g. "40 mm" or "height * 2".')
        .meta({ examples: ["40 mm", "height * 2"] }),
    })
    .describe(
      "Change an existing parameter's expression and recompute the model in one pass — the " +
        "cheapest edit path. Returns the new expression, its evaluated value, whether a recompute " +
        "ran, and recomputed_feature_count (features that re-evaluated; null when the running " +
        "Fusion cannot report it). Use this to drive dimensions instead of recreating geometry.",
    ),
  fusion_diagnostics: z
    .object({})
    .strict()
    .describe(
      "Readiness flags and cumulative reliability counters for this add-in: whether the " +
        "dispatch loop and an MCP server are up, whether a document is open, the live tool " +
        "inventory, total tool calls, total tool failures, and per-kind error counts. Safe to " +
        "call at any time, including before any other tool; values are counts and names only, " +
        "never messages or paths. Use this to decide whether a missed call was this add-in or " +
        "the client.",
    ),
  // Wave-3a: feature creation. Geometry is addressed by stored selection handle
  // ($selection_N from get_active_selection); dimensions are Fusion expression
  // strings. Defaults live in the add-in handlers, so they are documented in the
  // descriptions below rather than re-declared with .default() — the bridge
  // forwards the raw arguments and re-declaring a default would leak into the
  // JSON Schema the drift guard compares against the add-in.
  fillet: z
    .strictObject({
      edges: z
        .array(z.string())
        .describe('Stored selection handles of the edges to fillet, e.g. ["$selection_0"].')
        .meta({ examples: [["$selection_0", "$selection_1"]] }),
      radius: z
        .string()
        .describe("Fillet radius as a Fusion expression; a bare number is centimetres.")
        .meta({ examples: ["5 mm", "0.25 in"] }),
      is_tangent_chain: z
        .boolean()
        .optional()
        .describe("Also fillet edges tangentially connected to the input edges (default: true)."),
    })
    .describe(
      "Add a constant-radius fillet across one or more edges of the active design. " +
        "Edges are addressed by stored selection handle ($selection_0 from get_active_selection); " +
        'radius is a Fusion expression such as "5 mm". is_tangent_chain (default true) extends the ' +
        "fillet along tangentially connected edges. One fillet feature is created for the whole edge set.",
    ),
  chamfer: z
    .strictObject({
      edges: z
        .array(z.string())
        .describe('Stored selection handles of the edges to chamfer, e.g. ["$selection_0"].')
        .meta({ examples: [["$selection_0"]] }),
      distance: z
        .string()
        .describe("Chamfer offset distance as a Fusion expression; a bare number is centimetres.")
        .meta({ examples: ["2 mm", "0.1 in"] }),
    })
    .describe(
      "Add an equal-distance chamfer across one or more edges of the active design. " +
        "Edges are addressed by stored selection handle ($selection_0 from get_active_selection); " +
        'distance is a Fusion expression such as "2 mm" and offsets both sides of the edge equally.',
    ),
  hole: z
    .strictObject({
      face: z
        .string()
        .describe("Stored selection handle of the planar face the hole starts on.")
        .meta({ examples: ["$selection_0"] }),
      position: z
        .strictObject({
          x: z.number().describe("X coordinate in centimetres."),
          y: z.number().describe("Y coordinate in centimetres."),
          z: z.number().describe("Z coordinate in centimetres."),
        })
        .describe("Hole centre as a 3D point in centimetres, dropped onto the face along its normal."),
      diameter: z
        .string()
        .describe("Hole diameter as a Fusion expression; a bare number is centimetres.")
        .meta({ examples: ["8 mm", "0.25 in"] }),
      extent: z
        .enum(["distance", "through_all"])
        .optional()
        .describe("Hole extent: a fixed distance (needs depth) or through-all (default: distance)."),
      depth: z
        .string()
        .optional()
        .describe("Hole depth as a Fusion expression; required for extent=distance, else ignored.")
        .meta({ examples: ["10 mm"] }),
      direction: z
        .enum(["positive", "negative"])
        .optional()
        .describe("Which way the hole runs off the face normal (default: positive)."),
    })
    .describe(
      "Drill a simple hole at a point on a planar face of the active design. " +
        "The face and its positioning point place the hole; diameter is a Fusion expression. " +
        "Extent is a distance (needs a depth) or through-all, and direction picks which way the hole " +
        "runs off the face normal. The face must be planar.",
    ),
  rectangular_pattern: z
    .strictObject({
      entities: z
        .array(z.string())
        .describe("Stored selection handles of the entities to pattern; all must be the same type.")
        .meta({ examples: [["$selection_0"]] }),
      direction_one: z
        .string()
        .describe("Stored selection handle of the linear edge or axis defining the first direction.")
        .meta({ examples: ["$selection_1"] }),
      quantity_one: z
        .number()
        .describe("Number of instances in the first direction, a unitless count.")
        .meta({ examples: [3] }),
      distance_one: z
        .string()
        .describe("First-direction spacing as a Fusion expression; a bare number is centimetres.")
        .meta({ examples: ["20 mm"] }),
      direction_two: z
        .string()
        .optional()
        .describe("Optional handle of the edge or axis defining the second direction.")
        .meta({ examples: ["$selection_2"] }),
      quantity_two: z
        .number()
        .optional()
        .describe("Optional instance count in the second direction, a unitless count.")
        .meta({ examples: [2] }),
      distance_two: z
        .string()
        .optional()
        .describe("Second-direction spacing as a Fusion expression; a bare number is centimetres.")
        .meta({ examples: ["15 mm"] }),
      is_symmetric: z
        .boolean()
        .optional()
        .describe("Distribute instances symmetrically about the seed (default: false)."),
    })
    .describe(
      "Pattern bodies, faces, or features along one direction, optionally a second. " +
        "Entities are addressed by stored selection handle and must all be the same kind. " +
        "Each direction takes a linear edge or axis handle, an instance count, and a spacing expression. " +
        "A second direction needs all three of its arguments.",
    ),
  circular_pattern: z
    .strictObject({
      entities: z
        .array(z.string())
        .describe("Stored selection handles of the entities to pattern; all must be the same type.")
        .meta({ examples: [["$selection_0"]] }),
      axis: z
        .string()
        .describe("Handle of the linear edge, axis, or cylindrical face defining the rotation axis.")
        .meta({ examples: ["$selection_1"] }),
      quantity: z
        .number()
        .describe("Number of instances around the axis, a unitless count.")
        .meta({ examples: [6] }),
      total_angle: z
        .string()
        .optional()
        .describe("Total sweep as a Fusion angle expression; a bare number is degrees.")
        .meta({ examples: ["360 deg", "180 deg"] }),
      is_symmetric: z
        .boolean()
        .optional()
        .describe("Distribute instances symmetrically about the seed (default: false)."),
    })
    .describe(
      "Pattern bodies, faces, or features around an axis through a total angle. " +
        "Entities are addressed by stored selection handle and must all be the same kind. " +
        "The axis is a linear edge, construction axis, or cylindrical face handle; " +
        "the angle defaults to a full circle.",
    ),
  create_sketch: z
    .strictObject({
      plane: z
        .enum(["xy", "xz", "yz"])
        .describe("Base construction plane the sketch lies on.")
        .meta({ examples: ["xy"] }),
      curves: z
        .array(curveSchema)
        .describe(
          "Curves to draw, in centimetres. Endpoints that coincide chain into closed profiles, " +
            "so the order of curves does not matter.",
        )
        .meta({
          examples: [
            [
              { kind: "line", start: { x: 0, y: 0, z: 0 }, end: { x: 2, y: 0, z: 0 } },
              { kind: "line", start: { x: 2, y: 0, z: 0 }, end: { x: 2, y: 2, z: 0 } },
              { kind: "line", start: { x: 2, y: 2, z: 0 }, end: { x: 0, y: 2, z: 0 } },
              { kind: "line", start: { x: 0, y: 2, z: 0 }, end: { x: 0, y: 0, z: 0 } },
            ],
          ],
        }),
    })
    .describe(
      "Draw one or more curves on a base construction plane (xy, xz, or yz) of the root component. " +
        "Each curve is a line between two points, a circle about a centre and radius, or an arc about a " +
        "centre from a start point through a sweep; all coordinates and radii are in centimetres and arc " +
        "sweeps are in degrees (counter-clockwise positive). Returns the sketch handle plus one handle per " +
        "closed profile Fusion derived from the curves ($profile_0, ...); profiles are populated " +
        "automatically, and an open curve chain yields none. Give a profile handle to extrude or revolve " +
        "to make solid geometry.",
    ),
  extrude: z
    .strictObject({
      profile: z
        .string()
        .describe("Handle of the closed profile to sweep, from create_sketch.")
        .meta({ examples: ["$profile_0"] }),
      operation: z
        .enum(["new_body", "join", "cut", "intersect"])
        .optional()
        .describe("How the extruded geometry combines with existing bodies (default: new_body)."),
      extent: z
        .enum(["distance", "through_all", "symmetric"])
        .optional()
        .describe("Extrude extent: distance, through all geometry, or symmetric (default: distance)."),
      distance: z
        .string()
        .optional()
        .describe(
          "Extrude distance as a Fusion expression; a bare number is centimetres. Required for extent " +
            "distance and symmetric.",
        )
        .meta({ examples: ["10 mm", 2.5] }),
      direction: z
        .enum(["positive", "negative"])
        .optional()
        .describe("Which way a one-sided extent runs off the profile (default: positive)."),
    })
    .describe(
      "Sweep a closed profile into a solid body. The profile is a handle returned by create_sketch " +
        "($profile_0). operation controls how the new geometry combines with existing bodies (new_body by " +
        "default). extent is a fixed distance (needs the distance argument), through_all, or a symmetric " +
        "sweep about the profile plane (also needs distance); direction applies to the one-sided extents. " +
        "The created body is returned as a handle for appearance or selection tools.",
    ),
  revolve: z
    .strictObject({
      profile: z
        .string()
        .describe("Handle of the closed profile to revolve, from create_sketch.")
        .meta({ examples: ["$profile_0"] }),
      axis: z
        .string()
        .describe("Stored entity handle of the axis, or x, y, or z for a construction axis.")
        .meta({ examples: ["$selection_0", "y"] }),
      operation: z
        .enum(["new_body", "join", "cut", "intersect"])
        .optional()
        .describe("How the revolved geometry combines with existing bodies (default: new_body)."),
      angle: z
        .string()
        .optional()
        .describe("Total sweep as a Fusion angle expression; a bare number is degrees (default: full circle).")
        .meta({ examples: ["360 deg", "180 deg"] }),
    })
    .describe(
      "Sweep a closed profile about an axis through an angle to make a solid body. The profile is a handle " +
        "from create_sketch; the axis is a stored entity handle or one of the strings x, y, or z for the " +
        "root component's construction axes. The angle is a Fusion angle expression and defaults to a full " +
        "360-degree turn. operation controls how the new geometry combines with existing bodies.",
    ),
  create_component: z
    .strictObject({
      name: z
        .string()
        .describe("Name of the new component; must be unique enough for the caller to find later.")
        .meta({ examples: ["Bracket"] }),
    })
    .describe(
      "Add a new component to the root component's assembly and name it. The component is created by " +
        "adding an occurrence with an identity transform, then naming the component that occurrence owns; " +
        "the returned component handle identifies it for later selection.",
    ),
  create_body: z
    .strictObject({
      shape: z
        .enum(["box", "cylinder", "sphere"])
        .describe("Primitive shape to build.")
        .meta({ examples: ["box"] }),
      dimensions: dimensionsSchema,
      name: z
        .string()
        .optional()
        .describe("Optional body name; Fusion assigns one when omitted.")
        .meta({ examples: ["Housing"] }),
    })
    .describe(
      "Add a primitive box, cylinder, or sphere body to the root component. Dimensions are in centimetres: " +
        "a box needs length, width, and height; a cylinder needs radius and height; a sphere needs radius. " +
        "A parametric design wraps the body in a base feature on the timeline, a direct design adds it " +
        "directly. The returned body handle can be given to apply_appearance.",
    ),
  apply_appearance: z
    .strictObject({
      body: z
        .string()
        .describe("Stored handle of the body to recolour.")
        .meta({ examples: ["$body_0"] }),
      appearance: z
        .string()
        .describe("Name of the appearance in the library.")
        .meta({ examples: ["Steel", "Aluminum"] }),
      library: z
        .string()
        .optional()
        .describe("Material library for the appearance (default: Fusion 360 Material Library).")
        .meta({ examples: ["Fusion 360 Material Library"] }),
    })
    .describe(
      "Assign an appearance from a material library to a body. The body is a stored handle (from " +
        "create_body, extrude, or a selection); the appearance is named from the library, which defaults to " +
        "the Fusion 360 Material Library. The appearance is copied into the design and assigned to the body.",
    ),
  list_bodies: z
    .strictObject({})
    .describe(
      "List every solid and surface body in the root component, read-only. Each entry " +
        "reports name, is_solid, volume in cubic centimetres, area in square centimetres, " +
        "the tight-fitting bounding box, and face and edge counts. A design with no bodies " +
        "returns an empty list, not an error. Call this to learn what a design contains " +
        "before changing anything.",
    ),
  inspect_entity: z
    .strictObject({
      entity: z
        .string()
        .describe("Stored selection handle of the body, face, or edge to inspect.")
        .meta({ examples: ["$selection_0"] }),
    })
    .describe(
      "Report the geometry of one body, face, or edge by stored selection handle, " +
        "read-only. The reported fields depend on the kind: a body reports volume, area, " +
        "bounding box, and face and edge counts; a face reports area, centroid, bounding " +
        "box, and surface kind (plane, cylinder, cone, sphere, torus, elliptical cylinder, " +
        "elliptical cone, or nurbs); an edge reports length and bounding box. Use " +
        "get_active_selection first to capture the handle.",
    ),
  list_features: z
    .strictObject({})
    .describe(
      "List the design's timeline nodes, read-only: sketches, construction geometry, " +
        "canvas and decal inserts, joints, PMI, and features alike, each with its kind. " +
        "Every node reports name, timeline index, is_suppressed, a health label (healthy, " +
        "warning, error, suppressed, rolled back, or unknown), and the message Fusion " +
        "attaches to a warning or an error. A direct design has no timeline and reports an " +
        "empty list.",
    ),
  measure: z
    .strictObject({
      entity_one: z
        .string()
        .describe("Stored selection handle of the first entity to measure.")
        .meta({ examples: ["$selection_0"] }),
      entity_two: z
        .string()
        .describe("Stored selection handle of the second entity to measure.")
        .meta({ examples: ["$selection_1"] }),
      mode: z
        .enum(["distance", "angle"])
        .optional()
        .describe("What to measure: 'distance' for a minimum gap, 'angle' for a rotation.")
        .meta({ examples: ["distance"] }),
    })
    .describe(
      "Measure between two stored selection handles, read-only. Mode 'distance' (the " +
        "default) reports the minimum gap in centimetres; mode 'angle' reports the value in " +
        "radians and in degrees. The two modes accept different geometry: distance measures " +
        "bodies, faces, edges, and points, while angle rejects bodies and curved faces and " +
        "measures points, linear edges, axes, and planar faces -- an incompatible kind is " +
        "reported as invalid_value rather than passed to the API.",
    ),
  list_tool_categories: z.object({}).describe("List the available tools grouped by category; takes no arguments."),
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
 * When the add-in is unreachable the bridge still reports its own bridge-owned
 * tools (fusion_health, list_tool_categories), so the LLM can diagnose the
 * outage and discover the surface instead of an empty list with no explanation.
 */
async function handleListTools(monitor: ConnectionMonitor): Promise<{ tools: Tool[] }> {
  const { host, port } = monitor.endpoint;
  const result = await sendUpstream(
    host,
    port,
    { jsonrpc: "2.0", id: nextRequestId(), method: "tools/list" },
    LIST_TIMEOUT_MS,
  );

  if (!result.ok) return { tools: bridgeOwnedTools() };

  const success = asJsonRpcSuccess(result.message);
  if (success === null) {
    // A method-not-found error means the add-in predates tools/list: nothing
    // to proxy. Anything else is a protocol problem; report bridge-owned only.
    const error = asJsonRpcError(result.message);
    return { tools: error !== null && error.error.code === -32601 ? [] : bridgeOwnedTools() };
  }

  const parsed = ListToolsResultSchema.safeParse(success.result);
  if (!parsed.success) return { tools: bridgeOwnedTools() };

  const advertised: readonly Tool[] = parsed.data.tools;
  const byName = new Map<string, Tool>(advertised.map((tool) => [tool.name, tool]));

  const tools: Tool[] = [];
  for (const name of filterToolList(advertised.map((tool) => tool.name))) {
    const tool = byName.get(name);
    if (tool !== undefined) tools.push(tool);
  }
  // Bridge-owned tools have no upstream counterpart, so they are appended here
  // rather than filtered in: they stay advertised when the add-in is down.
  for (const bridgeTool of bridgeOwnedTools()) {
    if (!tools.some((tool) => tool.name === bridgeTool.name)) tools.push(bridgeTool);
  }

  return { tools };
}

/** The bridge-owned entries: answered locally, never proxied from upstream. */
function bridgeOwnedTools(): Tool[] {
  return [healthTool(), categoryTool()];
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

  // 1. Bridge-owned tools, answered locally and never forwarded.
  if (name === CATEGORY_TOOL) return toolJson(listToolCategories());
  if (name === HEALTH_TOOL) {
    const report: HealthReport = await monitor.health();
    return toolJson(report);
  }

  // 2. Security gate, before any argument is inspected.
  const gate = gateToolCall(name);
  if (!gate.allowed) {
    return gateFailure(name, gate.reason ?? "not-allowed");
  }

  // 3. Validate arguments with zod before they cross the wire.
  const schema = TOOL_ARGS[name];
  if (schema !== undefined && args !== undefined) {
    const validated = schema.safeParse(args);
    if (!validated.success) {
      return invalidArguments(name, validated.error.issues);
    }
  }

  // 4. Forward through the state machine.
  const outcome = await monitor.send({ method: "tools/call", params: { name, arguments: args } }, CALL_TIMEOUT_MS);
  if (outcome.ok) return mapToolResult(outcome.message, name);

  // 5. Map the failure onto the tier that matches where it happened.
  return mapFailure(outcome.kind, outcome.detail, name, monitor);
}

/**
 * Converts an upstream reply into a tools/call result, honoring error tiers.
 *
 * A well-formed result is passed through UNCHANGED: the add-in owns the success
 * shape and its own structured error envelopes (`error_kind`/`message`/`hint`),
 * which must reach the LLM exactly as the add-in wrote them.
 */
function mapToolResult(message: unknown, name: string): ToolResult {
  const error = asJsonRpcError(message);
  if (error !== null) {
    // Tier (b): the add-in answered, but its dispatch layer caught a failure.
    // The upstream `message` is built from `str(exc)` and `data` carries a full
    // traceback (lib/mcp_server.py), so neither is echoed: the LLM gets the
    // code plus an actionable hint, and the cause stays in the add-in log.
    return toolFailure("tool_failed", `Tool '${name}' failed (code ${error.error.code}).`);
  }

  const success = asJsonRpcSuccess(message);
  if (success === null) return protocolFailure(name);

  const parsed = CallToolResultSchema.safeParse(success.result);
  if (!parsed.success) {
    return protocolFailure(name, "reply did not match the MCP CallToolResult schema");
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
      return timeoutFailure(host, port, CALL_TIMEOUT_MS, detail);
    case "forbidden":
      // Reachable but refused: an origin/identity problem, not an outage.
      return forbiddenFailure(host, port, detail);
    case "bridge-bug":
      return bridgeBugFailure(detail);
    default:
      return protocolFailure(name, detail);
  }
}

let requestCounter = 0;

/** Monotonic JSON-RPC ids for requests the bridge originates. */
function nextRequestId(): number {
  requestCounter = (requestCounter % 0xffff) + 1;
  return requestCounter;
}
