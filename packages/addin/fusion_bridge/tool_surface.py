"""Central definitions for the public MCP tool surface."""

# Tool name constants
CAPTURE_VIEWPORT = "capture_viewport"
GET_VIEWPORT = "get_viewport"
SET_VIEWPORT = "set_viewport"
FETCH_API_DOCUMENTATION = "fetch_api_documentation"
FETCH_ONLINE_DOCUMENTATION = "fetch_online_documentation"
FETCH_DESIGN_GUIDE = "fetch_design_guide"
GET_ACTIVE_SELECTION = "get_active_selection"

# Resource constants
RESOURCE_URI = "fusion://design-guide"
RESOURCE_NAME = "Autodesk Fusion Design Guide"
RESOURCE_DESCRIPTION = "Workflow guidance, API patterns, naming rules, and modeling habits for Autodesk Fusion."

STANDARD_VIEWS = ["front", "back", "left", "right", "top", "bottom", "isometric",
                  "iso_top_left", "iso_top_right", "iso_bottom_left", "iso_bottom_right"]
PROJECTIONS = ["orthographic", "perspective", "perspective_with_ortho_faces"]
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
    }
    if set(handlers) != _TOOL_NAMES:
        raise RuntimeError(f"Handler registry mismatch: {set(handlers) ^ _TOOL_NAMES}")
    return handlers
