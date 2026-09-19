"""Central definitions for the public MCP tool surface."""

# Tool name constants
CAPTURE_VIEWPORT = "capture_viewport"
GET_VIEWPORT = "get_viewport"
SET_VIEWPORT = "set_viewport"
FETCH_API_DOCUMENTATION = "fetch_api_documentation"
FETCH_ONLINE_DOCUMENTATION = "fetch_online_documentation"
FETCH_DESIGN_GUIDE = "fetch_design_guide"
GET_ACTIVE_SELECTION = "get_active_selection"

# Wave 2 — lifecycle, documents, parameters
FUSION_STATUS = "fusion_status"
LIST_DOCUMENTS = "list_documents"
NEW_DOCUMENT = "new_document"
OPEN_DOCUMENT = "open_document"
SAVE_DOCUMENT = "save_document"
EXPORT_DOCUMENT = "export_document"
CLOSE_DOCUMENT = "close_document"
GET_DOCUMENT_INFO = "get_document_info"
LIST_PARAMETERS = "list_parameters"
ADD_PARAMETER = "add_parameter"
MODIFY_PARAMETER = "modify_parameter"

# Resource constants
RESOURCE_URI = "fusion://design-guide"
RESOURCE_NAME = "Autodesk Fusion Design Guide"
RESOURCE_DESCRIPTION = "Workflow guidance, API patterns, naming rules, and modeling habits for Autodesk Fusion."

STANDARD_VIEWS = ["front", "back", "left", "right", "top", "bottom", "isometric",
                  "iso_top_left", "iso_top_right", "iso_bottom_left", "iso_bottom_right"]
PROJECTIONS = ["orthographic", "perspective", "perspective_with_ortho_faces"]

# ── Wave 2 shared enums ───────────────────────────────────────────────────
# Geometry/length values are numbers in centimeters unless the tool's own
# units field says otherwise.  Length/angle *expressions* ("25 mm", "w/2")
# are passed straight to the Fusion expression engine.
DESIGN_TYPES = ["parametric", "direct"]
EXPORT_FORMATS = ["step", "stl", "f3d", "iges", "obj", "pdf"]
STL_DENSITY = ["low", "medium", "high"]
STL_UNITS = ["mm", "cm", "in", "m"]
POINT_SCHEMA = {
    "type": "object",
    "properties": {
        axis: {"type": "number", "minimum": -1e12, "maximum": 1e12}
        for axis in ("x", "y", "z")
    },
    "required": ["x", "y", "z"], "additionalProperties": False,
}
CAMERA_SCHEMA = {
    "type": "object",
    "description": (
        "Camera snapshot from get_viewport. Coordinates/extents in cm; "
        "perspective_angle in degrees. Use alone to restore a camera."
    ),
    "properties": {
        "eye": POINT_SCHEMA, "target": POINT_SCHEMA, "up_vector": POINT_SCHEMA,
        "projection": {"type": "string", "enum": PROJECTIONS},
        "extents": {
            "type": "object", "description": "Required for orthographic cameras only, in cm.",
            "properties": {k: {"type": "number", "minimum": 1e-9, "maximum": 1e12} for k in ("width", "height")},
            "required": ["width", "height"], "additionalProperties": False,
        },
        "perspective_angle": {"type": "number", "minimum": 0.01, "maximum": 179,
                              "description": "Required for perspective cameras only; angle in degrees."},
    },
    "required": ["eye", "target", "up_vector", "projection"], "additionalProperties": False,
}

# Each tool: {"name", "description", "inputSchema"}
TOOL_DEFINITIONS = [
    {
        "name": CAPTURE_VIEWPORT,
        "description": (
            "Capture the active Fusion viewport as a PNG. Optional view and fit are temporary: "
            "the original camera is restored even on failure. Background can be viewport, "
            "transparent, or #RRGGBB. Crop uses pixels in the rendered image, origin top-left. "
            "Returns only the cropped region when crop is provided; limit 16 megapixels."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {
                    "type": "integer",
                    "minimum": 0, "maximum": 8192,
                    "description": "Rendered image width in pixels (default: 800; 0 uses viewport width)",
                },
                "height": {
                    "type": "integer",
                    "minimum": 0, "maximum": 8192,
                    "description": "Rendered image height in pixels (default: 600; 0 uses viewport height)",
                },
                "view": {
                    "type": "string", "enum": STANDARD_VIEWS,
                    "description": "Temporary ViewCube-relative standard view; omit to keep current view.",
                },
                "fit": {
                    "type": "boolean",
                    "description": "Temporarily fit all graphics before capture (default: false).",
                },
                "background": {
                    "type": "string",
                    "description": "viewport (default), transparent, or a solid #RRGGBB color.",
                },
                "anti_aliasing": {"type": "boolean", "description": "Smooth rendered edges (default: true)."},
                "crop": {
                    "type": "object",
                    "description": "Rectangle inside the rendered image; output dimensions equal crop width/height.",
                    "properties": {k: {"type": "integer", "minimum": 0 if k in ("x", "y") else 1, "maximum": 8192}
                                   for k in ("x", "y", "width", "height")},
                    "required": ["x", "y", "width", "height"], "additionalProperties": False,
                },
            },
        },
    },
    {
        "name": GET_VIEWPORT,
        "description": (
            "Read active viewport pixel dimensions and camera eye, target, up_vector, projection, "
            "and extents or perspective_angle. Lengths are cm and angles degrees. "
            "Pass the returned camera object to set_viewport to restore it. All clients share this viewport."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": SET_VIEWPORT,
        "description": (
            "Control the active Fusion camera. Changes apply in order: projection/view, fit, orbit, pan, zoom. "
            "Standard views follow the user's ViewCube orientation. Orbit angles use right-hand rotation: "
            "yaw about camera up, pitch about camera right, roll about the viewing direction. "
            "Pan translates the camera along screen right/up in cm. Zoom >1 zooms in; <1 zooms out. "
            "Alternatively pass a complete camera snapshot alone. Returns actual camera state. "
            "This changes the shared viewport for all clients, without modifying model geometry."
        ),
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "camera": CAMERA_SCHEMA,
                "view": {"type": "string", "enum": STANDARD_VIEWS},
                "projection": {"type": "string", "enum": PROJECTIONS},
                "fit": {"type": "boolean", "description": "Fit all graphics (default: false)."},
                "orbit": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        k: {"type": "number", "minimum": -360, "maximum": 360}
                        for k in ("yaw", "pitch", "roll")
                    },
                },
                "pan": {"type": "object", "additionalProperties": False,
                        "properties": {k: {"type": "number", "minimum": -1e9, "maximum": 1e9} for k in ("x", "y")}},
                "zoom": {"type": "number", "minimum": 0.01, "maximum": 100},
                "description": {"type": "string"},
            },
        },
    },
    {
        "name": FETCH_API_DOCUMENTATION,
        "description": (
            "Search live Fusion API metadata through runtime introspection. "
            "Returns scored results with class overviews, properties, "
            "and function signatures."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": (
                        "Search term (e.g. 'BRepBody', 'sketches', "
                        "'adsk.fusion.Sketch.add')"
                    ),
                },
                "category": {
                    "type": "string",
                    "description": (
                        "Search category: class_name, member_name, description, or all"
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 3)",
                },
            },
            "required": ["search_term"],
        },
    },
    {
        "name": FETCH_ONLINE_DOCUMENTATION,
        "description": (
            "Fetch Autodesk cloudhelp documentation for a specific "
            "Fusion API class or member."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "API class name (e.g. 'BRepBody', 'Sketch')",
                },
                "member_name": {
                    "type": "string",
                    "description": "Optional member name (e.g. 'add', 'name')",
                },
            },
            "required": ["class_name"],
        },
    },
    {
        "name": FETCH_DESIGN_GUIDE,
        "description": (
            "Read the bundled Fusion design guide with workflow guidance, "
            "API patterns, naming rules, and modeling habits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": GET_ACTIVE_SELECTION,
        "description": (
            "Get the objects currently selected by the user in the Fusion 360 viewport. "
            "Returns detailed info per item (type, name, entityToken, parent component, "
            "and type-specific properties like area, volume, material)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": FUSION_STATUS,
        "description": (
            "Report the state of the running Fusion: version, active document name, modified flag, "
            "design units, design type (parametric or direct), active workspace, timeline feature count, "
            "and how long this add-in has been running. Works with no document open; document fields "
            "are then null. Use this first to learn what you are working with."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": LIST_DOCUMENTS,
        "description": (
            "List every document currently open in Fusion, with name, active flag, modified flag, "
            "design type, and saved path (null when never saved). Use fusion_status for the active "
            "document's deeper detail."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": NEW_DOCUMENT,
        "description": (
            "Create and activate a new Fusion design document with the given name. The optional "
            "design_type selects parametric (timeline history, default) or direct (history-free) "
            "modeling; switching to direct removes the timeline. Returns the document name and "
            "the design type that was applied."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "description": "Name for the new document."},
                "design_type": {
                    "type": "string",
                    "enum": DESIGN_TYPES,
                    "description": "Parametric (default) keeps a timeline; direct is history-free.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": OPEN_DOCUMENT,
        "description": (
            "Open a previously saved Fusion file (.f3d, .f3z, .step, .iges, .smt, .sat, .dwg, ...) "
            "by path and activate it. Returns the document name and its modified flag. The path is "
            "passed to Fusion's open; local file paths are supported."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "Path of the file to open."},
            },
            "required": ["path"],
        },
    },
    {
        "name": SAVE_DOCUMENT,
        "description": (
            "Save the active document. Omit path to save in place (fails with a clear error if the "
            "document has never been saved). Provide path to save-as, which also works for a never-saved "
            "document; the path's folder is used as the save location and its file name as the document "
            "name. Returns the resulting saved path."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Save-as target; omit to save the existing file in place.",
                },
            },
        },
    },
    {
        "name": EXPORT_DOCUMENT,
        "description": (
            "Export the active design to step, stl, f3d, iges, obj, or pdf, writing to the given path "
            "and reporting the file size in bytes. Requires an active design; returns a clear error "
            "otherwise. For stl, stl_density maps to mesh refinement (low/medium/high, default medium) "
            "and stl_units selects the units the unitless STL numbers represent (default: the design's "
            "units). Not every Fusion build can emit every format; unsupported combinations are "
            "reported rather than silently ignored."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "format": {"type": "string", "enum": EXPORT_FORMATS, "description": "Export format."},
                "path": {"type": "string", "description": "Output file path."},
                "stl_density": {
                    "type": "string",
                    "enum": STL_DENSITY,
                    "description": "STL mesh refinement (default: medium).",
                },
                "stl_units": {
                    "type": "string",
                    "enum": STL_UNITS,
                    "description": "Units the unitless STL numbers represent (default: design units).",
                },
            },
            "required": ["format", "path"],
        },
    },
    {
        "name": CLOSE_DOCUMENT,
        "description": (
            "Close the active document, or the one named by document_name. Set save true to persist "
            "changes first (the document must already have a save location; otherwise save it with "
            "save_document first). Unsaved changes are discarded when save is false or omitted. "
            "Returns closed: true/false."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "document_name": {
                    "type": "string",
                    "description": "Document to close; omit for the active one.",
                },
                "save": {"type": "boolean", "description": "Save in place before closing (default: false)."},
            },
        },
    },
    {
        "name": GET_DOCUMENT_INFO,
        "description": (
            "Report the active document's name, saved path, default length units, design type, "
            "modified flag, and version. Returns a clear error when no document is open."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": LIST_PARAMETERS,
        "description": (
            "List every user and model parameter in the active design. Each entry carries name, "
            "expression (Fusion expression string, e.g. \"25 mm\" or \"width / 2\"), unit, value "
            "(the evaluated number; lengths are in the parameter's internal centimeter units), "
            "parameter_type (user or model), and driven (true when the model computes the value)."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": ADD_PARAMETER,
        "description": (
            "Add a user parameter to the active design. The expression is a Fusion expression string "
            "(\"3 mm\", \"width/2\", \"45 deg\") and is consumed by the expression engine, so units "
            "inside it are honored. The optional unit string (default mm) labels the parameter. "
            "Fails with a clear error on a duplicate name or an invalid expression."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "description": "Parameter name; must be unique."},
                "expression": {
                    "type": "string",
                    "description": "Fusion expression, e.g. \"3 mm\" or \"width/2\".",
                },
                "unit": {"type": "string", "description": "Parameter unit label (default: mm)."},
            },
            "required": ["name", "expression"],
        },
    },
    {
        "name": MODIFY_PARAMETER,
        "description": (
            "Change an existing parameter's expression and recompute the model in one pass — the "
            "cheapest edit path. Returns the new expression, its evaluated value, whether a recompute "
            "ran, and recomputed_feature_count (features that re-evaluated; null when the running "
            "Fusion cannot report it). Use this to drive dimensions instead of recreating geometry."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "description": "Existing parameter name."},
                "expression": {
                    "type": "string",
                    "description": "New Fusion expression, e.g. \"40 mm\" or \"height * 2\".",
                },
            },
            "required": ["name", "expression"],
        },
    },
]

_TOOL_NAMES = {t["name"] for t in TOOL_DEFINITIONS}


def build_tool_handlers(
    *,
    capture_viewport,
    get_viewport,
    set_viewport,
    fetch_api_documentation,
    fetch_online_documentation,
    fetch_design_guide,
    get_active_selection,
    fusion_status,
    list_documents,
    new_document,
    open_document,
    save_document,
    export_document,
    close_document,
    get_document_info,
    list_parameters,
    add_parameter,
    modify_parameter,
):
    """Build a dict mapping tool name to handler function.

    All tool names must have a corresponding handler. A RuntimeError
    is raised if the handler keys don't match TOOL_DEFINITIONS.
    """
    handlers = {
        CAPTURE_VIEWPORT: capture_viewport,
        GET_VIEWPORT: get_viewport,
        SET_VIEWPORT: set_viewport,
        FETCH_API_DOCUMENTATION: fetch_api_documentation,
        FETCH_ONLINE_DOCUMENTATION: fetch_online_documentation,
        FETCH_DESIGN_GUIDE: fetch_design_guide,
        GET_ACTIVE_SELECTION: get_active_selection,
        FUSION_STATUS: fusion_status,
        LIST_DOCUMENTS: list_documents,
        NEW_DOCUMENT: new_document,
        OPEN_DOCUMENT: open_document,
        SAVE_DOCUMENT: save_document,
        EXPORT_DOCUMENT: export_document,
        CLOSE_DOCUMENT: close_document,
        GET_DOCUMENT_INFO: get_document_info,
        LIST_PARAMETERS: list_parameters,
        ADD_PARAMETER: add_parameter,
        MODIFY_PARAMETER: modify_parameter,
    }
    if set(handlers) != _TOOL_NAMES:
        raise RuntimeError(f"Handler registry mismatch: {set(handlers) ^ _TOOL_NAMES}")
    return handlers
