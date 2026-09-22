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

# Wave 2 — diagnostics
FUSION_DIAGNOSTICS = "fusion_diagnostics"

# Wave 3a — features
FILLET = "fillet"
CHAMFER = "chamfer"
HOLE = "hole"
RECTANGULAR_PATTERN = "rectangular_pattern"
CIRCULAR_PATTERN = "circular_pattern"

# Wave 3b — sketch, extrude/revolve, structure, and appearance
CREATE_SKETCH = "create_sketch"
EXTRUDE = "extrude"
REVOLVE = "revolve"
CREATE_COMPONENT = "create_component"
CREATE_BODY = "create_body"
APPLY_APPEARANCE = "apply_appearance"

# Wave 4 — read-only inspection
LIST_BODIES = "list_bodies"
INSPECT_ENTITY = "inspect_entity"
LIST_FEATURES = "list_features"
MEASURE = "measure"

# Tool categories.  A tool belongs to exactly one; ``build_tool_handlers`` and
# the contract tests enforce that every definition carries one.
CATEGORY_VIEWPORT = "viewport"
CATEGORY_SELECTION = "selection"
CATEGORY_DOCUMENTS = "documents"
CATEGORY_PARAMETERS = "parameters"
CATEGORY_DOCUMENTATION = "documentation"
CATEGORY_DIAGNOSTICS = "diagnostics"
CATEGORY_FEATURES = "features"
CATEGORY_INSPECTION = "inspection"
CATEGORIES = (
    CATEGORY_VIEWPORT,
    CATEGORY_SELECTION,
    CATEGORY_DOCUMENTS,
    CATEGORY_PARAMETERS,
    CATEGORY_DOCUMENTATION,
    CATEGORY_DIAGNOSTICS,
    CATEGORY_FEATURES,
    CATEGORY_INSPECTION,
)

# Resource constants
RESOURCE_URI = "fusion://design-guide"
RESOURCE_NAME = "Autodesk Fusion Design Guide"
RESOURCE_DESCRIPTION = "Workflow guidance, API patterns, naming rules, and modeling habits for Autodesk Fusion."

STANDARD_VIEWS = [
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
]
PROJECTIONS = ["orthographic", "perspective", "perspective_with_ortho_faces"]

# ── Wave 2 shared enums ───────────────────────────────────────────────────
# Geometry/length values are numbers in centimeters unless the tool's own
# units field says otherwise.  Length/angle *expressions* ("25 mm", "w/2")
# are passed straight to the Fusion expression engine.
DESIGN_TYPES = ["parametric", "direct"]
EXPORT_FORMATS = ["step", "stl", "f3d", "iges", "obj", "pdf"]
STL_DENSITY = ["low", "medium", "high"]
STL_UNITS = ["mm", "cm", "in", "m"]

# The unit a tool's bare numbers are stated in.  Mirrors the conversion table
# in value_builders.CM_PER_UNIT — the drift guard pins the bridge copy of this
# enum, and tool_surface cannot import that module (it must stay pure-data so
# the contract generator can import it outside Fusion), so the two are held in
# sync by tests/tools/test_units.py.
LENGTH_UNITS = ["mm", "cm", "in", "m"]

# A reusable "units" property: every dimension-bearing tool carries it.  Bare
# numbers in that call are read in this unit; expression strings carry their
# own unit and are never rescaled.  Defaults to centimetres, the API's internal
# unit, so a call that omits it behaves exactly as before.
UNITS_PROPERTY = {
    "type": "string",
    "enum": LENGTH_UNITS,
    "description": (
        "Unit for every bare number in this call; expression strings carry their "
        "own unit and are never rescaled. Default is cm."
    ),
    "examples": ["mm"],
}

# ── Wave 3b shared enums ───────────────────────────────────────────────────
# Sketch geometry lives on one of the three base construction planes.  An
# extrude combines its new geometry with existing bodies and sweeps it by a
# distance, through everything, or symmetrically about the profile plane.
SKETCH_PLANES = ["xy", "xz", "yz"]
FEATURE_OPERATIONS = ["new_body", "join", "cut", "intersect"]
EXTRUDE_EXTENTS = ["distance", "through_all", "symmetric"]
DIRECTIONS = ["positive", "negative"]
BODY_SHAPES = ["box", "cylinder", "sphere"]
DEFAULT_APPEARANCE_LIBRARY = "Fusion 360 Material Library"

# ── Wave 4 shared enums ───────────────────────────────────────────────────
# The two measurement APIs take different entity kinds, so the mode is part of
# the contract: distance is a minimum gap in centimetres, angle is a rotation in
# radians (reported in degrees too) between two directions.
MEASURE_MODES = ["distance", "angle"]
POINT_SCHEMA = {
    "type": "object",
    "description": "A 3D position or direction vector; x, y, and z are in centimeters.",
    "properties": {
        axis: {
            "type": "number",
            "minimum": -1e12,
            "maximum": 1e12,
            "description": f"{axis.upper()} component in centimeters.",
        }
        for axis in ("x", "y", "z")
    },
    "required": ["x", "y", "z"],
    "additionalProperties": False,
}
# Geometry points on sketch curves: like POINT_SCHEMA, but each component may be
# a bare number in the tool's units or a Fusion expression string.  CAMERA_SCHEMA
# keeps the plain POINT_SCHEMA: camera coordinates are not physical dimensions
# and never carry units.
CURVE_POINT_SCHEMA = {
    "type": "object",
    "description": (
        "A 3D point on a sketch curve; each component is a bare number in the "
        "tool's units (default cm) or a Fusion expression string."
    ),
    "properties": {
        axis: {
            "type": ["string", "number"],
            "description": (
                f"{axis.upper()} component; a bare number is this tool's "
                "units (default cm), or a Fusion expression."
            ),
        }
        for axis in ("x", "y", "z")
    },
    "required": ["x", "y", "z"],
    "additionalProperties": False,
}

# The three curve variants share one object schema discriminated by ``kind``.
# The owned validator's vocabulary has no ``oneOf``; the per-variant required
# members are enforced by the handler, which reports them as invalid_value.
CURVE_SCHEMA = {
    "type": "object",
    "description": (
        "One sketch curve: a line, a circle, or an arc, told apart by 'kind'. "
        "Points are in centimetres; a line needs start and end, a circle needs "
        "center and radius, and an arc needs center, start, and sweep degrees."
    ),
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["line", "circle", "arc"],
            "description": "Which curve this is, and which members are required.",
        },
        "start": CURVE_POINT_SCHEMA,
        "end": CURVE_POINT_SCHEMA,
        "center": CURVE_POINT_SCHEMA,
        "radius": {
            "type": ["string", "number"],
            "description": "Circle radius as a Fusion expression, or a bare number in this tool's units (default cm).",
            "examples": [1.0, "5 mm"],
        },
        "sweep": {
            "type": "number",
            "minimum": -360,
            "maximum": 360,
            "description": "Arc sweep in degrees; positive is counter-clockwise.",
            "examples": [90],
        },
    },
    "required": ["kind"],
    "additionalProperties": False,
}
# Dimensions are discriminated by 'shape'; the validator has no oneOf, so the
# three variants share one object schema and the handler enforces that a box
# has length/width/height, a cylinder radius/height, and a sphere radius.
DIMENSIONS_SCHEMA = {
    "type": "object",
    "description": (
        "Body dimensions in centimetres; which members are required depends on "
        "the shape: box needs length, width, and height; cylinder needs radius "
        "and height; sphere needs radius alone."
    ),
    "properties": {
        "length": {
            "type": ["string", "number"],
            "description": (
                "Box length along the x axis as a Fusion expression, or a bare "
                "number in this tool's units (default cm)."
            ),
            "examples": [2.0, "20 mm"],
        },
        "width": {
            "type": ["string", "number"],
            "description": (
                "Box width along the y axis as a Fusion expression, or a bare "
                "number in this tool's units (default cm)."
            ),
            "examples": [2.0, "20 mm"],
        },
        "height": {
            "type": ["string", "number"],
            "description": (
                "Box or cylinder height along the z axis as a Fusion expression, "
                "or a bare number in this tool's units (default cm)."
            ),
            "examples": [3.0, "30 mm"],
        },
        "radius": {
            "type": ["string", "number"],
            "description": (
                "Cylinder or sphere radius as a Fusion expression, or a bare "
                "number in this tool's units (default cm)."
            ),
            "examples": [1.0, "5 mm"],
        },
    },
    "additionalProperties": False,
}
CAMERA_SCHEMA = {
    "type": "object",
    "description": (
        "Camera snapshot from get_viewport. Coordinates/extents in cm; "
        "perspective_angle in degrees. Use alone to restore a camera."
    ),
    "properties": {
        "eye": POINT_SCHEMA,
        "target": POINT_SCHEMA,
        "up_vector": POINT_SCHEMA,
        "projection": {
            "type": "string",
            "enum": PROJECTIONS,
            "description": "Camera projection; orthographic uses extents, perspective uses perspective_angle.",
        },
        "extents": {
            "type": "object",
            "description": "Required for orthographic cameras only, in cm.",
            "properties": {
                "width": {
                    "type": "number",
                    "minimum": 1e-9,
                    "maximum": 1e12,
                    "description": "View volume width in centimeters.",
                },
                "height": {
                    "type": "number",
                    "minimum": 1e-9,
                    "maximum": 1e12,
                    "description": "View volume height in centimeters.",
                },
            },
            "required": ["width", "height"],
            "additionalProperties": False,
        },
        "perspective_angle": {
            "type": "number",
            "minimum": 0.01,
            "maximum": 179,
            "description": "Required for perspective cameras only; angle in degrees.",
        },
    },
    "required": ["eye", "target", "up_vector", "projection"],
    "additionalProperties": False,
}

# Each tool: {"name", "category", "description", "inputSchema"}
TOOL_DEFINITIONS = [
    {
        "name": CAPTURE_VIEWPORT,
        "category": CATEGORY_VIEWPORT,
        "description": (
            "Capture the active Fusion viewport as a PNG. Optional view and fit are temporary: "
            "the original camera is restored even on failure. Background can be viewport, "
            "transparent, or #RRGGBB. Crop uses pixels in the rendered image, origin top-left. "
            "Returns only the cropped region when crop is provided; limit 16 megapixels."
        ),
        "inputSchema": {
            "type": "object",
            "description": "Capture options; all properties are optional.",
            "properties": {
                "width": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 8192,
                    "description": "Rendered image width in pixels (default: 800; 0 uses viewport width)",
                    "examples": [800, 1920],
                },
                "height": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 8192,
                    "description": "Rendered image height in pixels (default: 600; 0 uses viewport height)",
                    "examples": [600, 1080],
                },
                "view": {
                    "type": "string",
                    "enum": STANDARD_VIEWS,
                    "description": "Temporary ViewCube-relative standard view; omit to keep current view.",
                    "examples": ["isometric", "front"],
                },
                "fit": {
                    "type": "boolean",
                    "description": "Temporarily fit all graphics before capture (default: false).",
                },
                "background": {
                    "type": "string",
                    "description": "viewport (default), transparent, or a solid #RRGGBB color.",
                    "examples": ["viewport", "transparent", "#FFFFFF"],
                },
                "anti_aliasing": {"type": "boolean", "description": "Smooth rendered edges (default: true)."},
                "crop": {
                    "type": "object",
                    "description": "Rectangle inside the rendered image; output dimensions equal crop width/height.",
                    "properties": {
                        "x": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 8192,
                            "description": "Left edge of the crop region, in pixels from the image's left side.",
                        },
                        "y": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 8192,
                            "description": "Top edge of the crop region, in pixels from the image's top side.",
                        },
                        "width": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 8192,
                            "description": "Crop region width in pixels.",
                        },
                        "height": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 8192,
                            "description": "Crop region height in pixels.",
                        },
                    },
                    "required": ["x", "y", "width", "height"],
                    "additionalProperties": False,
                },
            },
        },
    },
    {
        "name": GET_VIEWPORT,
        "category": CATEGORY_VIEWPORT,
        "description": (
            "Read active viewport pixel dimensions and camera eye, target, up_vector, projection, "
            "and extents or perspective_angle. Lengths are cm and angles degrees. "
            "Pass the returned camera object to set_viewport to restore it. All clients share this viewport."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "description": "No arguments; the active viewport is read.",
        },
    },
    {
        "name": SET_VIEWPORT,
        "category": CATEGORY_VIEWPORT,
        "description": (
            "Control the active Fusion camera. Changes apply in order: projection/view, fit, orbit, pan, zoom. "
            "Standard views follow the user's ViewCube orientation. Orbit angles use right-hand rotation: "
            "yaw about camera up, pitch about camera right, roll about the viewing direction. "
            "Pan translates the camera along screen right/up in cm. Zoom >1 zooms in; <1 zooms out. "
            "Alternatively pass a complete camera snapshot alone. Returns actual camera state. "
            "This changes the shared viewport for all clients, without modifying model geometry."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Camera controls; pass either a camera snapshot or relative controls.",
            "properties": {
                "camera": CAMERA_SCHEMA,
                "view": {
                    "type": "string",
                    "enum": STANDARD_VIEWS,
                    "description": "Standard ViewCube orientation to apply.",
                    "examples": ["front", "iso_top_right"],
                },
                "projection": {
                    "type": "string",
                    "enum": PROJECTIONS,
                    "description": "Camera projection; orthographic uses extents, perspective uses perspective_angle.",
                },
                "fit": {"type": "boolean", "description": "Fit all graphics (default: false)."},
                "orbit": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": "Right-handed rotation angles in degrees about the camera axes.",
                    "properties": {
                        "yaw": {
                            "type": "number",
                            "minimum": -360,
                            "maximum": 360,
                            "description": "Rotation about the camera's up vector, in degrees.",
                            "examples": [30],
                        },
                        "pitch": {
                            "type": "number",
                            "minimum": -360,
                            "maximum": 360,
                            "description": "Rotation about the camera's right vector, in degrees.",
                            "examples": [-15],
                        },
                        "roll": {
                            "type": "number",
                            "minimum": -360,
                            "maximum": 360,
                            "description": "Rotation about the viewing direction, in degrees.",
                        },
                    },
                },
                "pan": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": "Camera translation along screen right and up, in centimeters.",
                    "properties": {
                        "x": {
                            "type": "number",
                            "minimum": -1e9,
                            "maximum": 1e9,
                            "description": "Displacement along screen right, in centimeters.",
                            "examples": [5],
                        },
                        "y": {
                            "type": "number",
                            "minimum": -1e9,
                            "maximum": 1e9,
                            "description": "Displacement along screen up, in centimeters.",
                            "examples": [2.5],
                        },
                    },
                },
                "zoom": {
                    "type": "number",
                    "minimum": 0.01,
                    "maximum": 100,
                    "description": "Dimensionless zoom factor; a ratio where 1 is the current scale.",
                    "examples": [2],
                },
                "description": {
                    "type": "string",
                    "description": "Optional caller note recorded with the view change; it is not rendered.",
                },
            },
        },
    },
    {
        "name": FETCH_API_DOCUMENTATION,
        "category": CATEGORY_DOCUMENTATION,
        "description": (
            "Search live Fusion API metadata through runtime introspection. "
            "Returns scored results with class overviews, properties, "
            "and function signatures."
        ),
        "inputSchema": {
            "type": "object",
            "description": "Search criteria; search_term is required.",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": ("Search term (e.g. 'BRepBody', 'sketches', 'adsk.fusion.Sketch.add')"),
                    "examples": ["BRepBody", "sketches"],
                },
                "category": {
                    "type": "string",
                    "description": ("Search category: class_name, member_name, description, or all"),
                    "examples": ["class_name", "all"],
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 3)",
                    "examples": [5],
                },
            },
            "required": ["search_term"],
        },
    },
    {
        "name": FETCH_ONLINE_DOCUMENTATION,
        "category": CATEGORY_DOCUMENTATION,
        "description": ("Fetch Autodesk cloudhelp documentation for a specific Fusion API class or member."),
        "inputSchema": {
            "type": "object",
            "description": "Class and member to look up; class_name is required.",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "API class name (e.g. 'BRepBody', 'Sketch')",
                    "examples": ["BRepBody", "Sketch"],
                },
                "member_name": {
                    "type": "string",
                    "description": "Optional member name (e.g. 'add', 'name')",
                    "examples": ["add"],
                },
            },
            "required": ["class_name"],
        },
    },
    {
        "name": FETCH_DESIGN_GUIDE,
        "category": CATEGORY_DOCUMENTATION,
        "description": (
            "Read the bundled Fusion design guide with workflow guidance, "
            "API patterns, naming rules, and modeling habits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "description": "No arguments; the bundled guide is returned.",
        },
    },
    {
        "name": GET_ACTIVE_SELECTION,
        "category": CATEGORY_SELECTION,
        "description": (
            "Get the objects currently selected by the user in the Fusion 360 viewport. "
            "Returns detailed info per item (type, name, entityToken, parent component, "
            "and type-specific properties like area, volume, material)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "description": "No arguments; the user's current selection is read.",
        },
    },
    {
        "name": FUSION_STATUS,
        "category": CATEGORY_DIAGNOSTICS,
        "description": (
            "Report the state of the running Fusion: version, active document name, modified flag, "
            "design units, design type (parametric or direct), active workspace, timeline feature count, "
            "and how long this add-in has been running. Works with no document open; document fields "
            "are then null. Use this first to learn what you are working with."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
            "description": "No arguments; the running Fusion state is reported.",
        },
    },
    {
        "name": LIST_DOCUMENTS,
        "category": CATEGORY_DOCUMENTS,
        "description": (
            "List every document currently open in Fusion, with name, active flag, modified flag, "
            "design type, and saved path (null when never saved). Use fusion_status for the active "
            "document's deeper detail."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
            "description": "No arguments; all open documents are listed.",
        },
    },
    {
        "name": NEW_DOCUMENT,
        "category": CATEGORY_DOCUMENTS,
        "description": (
            "Create and activate a new Fusion design document with the given name. The optional "
            "design_type selects parametric (timeline history, default) or direct (history-free) "
            "modeling; switching to direct removes the timeline. Returns the document name and "
            "the design type that was applied."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "New document settings; name is required.",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the new document.",
                    "examples": ["Bracket"],
                },
                "design_type": {
                    "type": "string",
                    "enum": DESIGN_TYPES,
                    "description": "Parametric (default) keeps a timeline; direct is history-free.",
                    "examples": ["parametric"],
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": OPEN_DOCUMENT,
        "category": CATEGORY_DOCUMENTS,
        "description": (
            "Open a previously saved Fusion file (.f3d, .f3z, .step, .iges, .smt, .sat, .dwg, ...) "
            "by path and activate it. Returns the document name and its modified flag. The path is "
            "passed to Fusion's open; local file paths are supported."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Document to open; path is required.",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to open.",
                    "examples": ["/home/user/designs/bracket.f3d"],
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": SAVE_DOCUMENT,
        "category": CATEGORY_DOCUMENTS,
        "description": (
            "Save the active document. Omit path to save in place (fails with a clear error if the "
            "document has never been saved). Provide path to save-as, which also works for a never-saved "
            "document; the path's folder is used as the save location and its file name as the document "
            "name. Returns the resulting saved path."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Save options; omit every property to save in place.",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Save-as target; omit to save the existing file in place.",
                    "examples": ["/home/user/designs/bracket-v2.f3d"],
                },
            },
        },
    },
    {
        "name": EXPORT_DOCUMENT,
        "category": CATEGORY_DOCUMENTS,
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
            "description": "Export target and format; format and path are required.",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": EXPORT_FORMATS,
                    "description": "Export format.",
                    "examples": ["stl"],
                },
                "path": {
                    "type": "string",
                    "description": "Output file path.",
                    "examples": ["/home/user/exports/bracket.stl"],
                },
                "stl_density": {
                    "type": "string",
                    "enum": STL_DENSITY,
                    "description": "STL mesh refinement (default: medium).",
                    "examples": ["high"],
                },
                "stl_units": {
                    "type": "string",
                    "enum": STL_UNITS,
                    "description": "Units the unitless STL numbers represent (default: design units).",
                    "examples": ["mm"],
                },
            },
            "required": ["format", "path"],
        },
    },
    {
        "name": CLOSE_DOCUMENT,
        "category": CATEGORY_DOCUMENTS,
        "description": (
            "Close the active document, or the one named by document_name. Set save true to persist "
            "changes first (the document must already have a save location; otherwise save it with "
            "save_document first). Unsaved changes are discarded when save is false or omitted. "
            "Returns closed: true/false."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Close options; every property is optional.",
            "properties": {
                "document_name": {
                    "type": "string",
                    "description": "Document to close; omit for the active one.",
                    "examples": ["bracket"],
                },
                "save": {"type": "boolean", "description": "Save in place before closing (default: false)."},
            },
        },
    },
    {
        "name": GET_DOCUMENT_INFO,
        "category": CATEGORY_DOCUMENTS,
        "description": (
            "Report the active document's name, saved path, default length units, design type, "
            "modified flag, and version. Returns a clear error when no document is open."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
            "description": "No arguments; the active document is described.",
        },
    },
    {
        "name": LIST_PARAMETERS,
        "category": CATEGORY_PARAMETERS,
        "description": (
            "List every user and model parameter in the active design. Each entry carries name, "
            'expression (Fusion expression string, e.g. "25 mm" or "width / 2"), unit, value '
            "(the evaluated number; lengths are in the parameter's internal centimeter units), "
            "parameter_type (user or model), and driven (true when the model computes the value)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
            "description": "No arguments; every parameter is listed.",
        },
    },
    {
        "name": ADD_PARAMETER,
        "category": CATEGORY_PARAMETERS,
        "description": (
            "Add a user parameter to the active design. The expression is a Fusion expression string "
            '("3 mm", "width/2", "45 deg") and is consumed by the expression engine, so units '
            "inside it are honored. The optional unit string (default mm) labels the parameter. "
            "Fails with a clear error on a duplicate name or an invalid expression."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Parameter definition; name and expression are required.",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Parameter name; must be unique.",
                    "examples": ["width"],
                },
                "expression": {
                    "type": "string",
                    "description": 'Fusion expression, e.g. "3 mm" or "width/2".',
                    "examples": ["3 mm", "width / 2"],
                },
                "unit": {
                    "type": "string",
                    "description": "Parameter unit label (default: mm).",
                    "examples": ["mm", "deg"],
                },
            },
            "required": ["name", "expression"],
        },
    },
    {
        "name": MODIFY_PARAMETER,
        "category": CATEGORY_PARAMETERS,
        "description": (
            "Change an existing parameter's expression and recompute the model in one pass — the "
            "cheapest edit path. Returns the new expression, its evaluated value, whether a recompute "
            "ran, and recomputed_feature_count (features that re-evaluated; null when the running "
            "Fusion cannot report it). Use this to drive dimensions instead of recreating geometry."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Parameter edit; name and expression are required.",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Existing parameter name.",
                    "examples": ["width"],
                },
                "expression": {
                    "type": "string",
                    "description": 'New Fusion expression, e.g. "40 mm" or "height * 2".',
                    "examples": ["40 mm", "height * 2"],
                },
            },
            "required": ["name", "expression"],
        },
    },
    {
        "name": FUSION_DIAGNOSTICS,
        "category": CATEGORY_DIAGNOSTICS,
        "description": (
            "Readiness flags and cumulative reliability counters for this add-in: whether the "
            "dispatch loop and an MCP server are up, whether a document is open, the live tool "
            "inventory, total tool calls, total tool failures, and per-kind error counts. Safe to "
            "call at any time, including before any other tool; values are counts and names only, "
            "never messages or paths. Use this to decide whether a missed call was this add-in or "
            "the client."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
            "description": "No arguments; the counters are read.",
        },
    },
    {
        "name": FILLET,
        "category": CATEGORY_FEATURES,
        "description": (
            "Add a constant-radius fillet across one or more edges of the active design. "
            "Edges are addressed by stored selection handle ($selection_0 from get_active_selection); "
            'radius is a Fusion expression such as "5 mm". is_tangent_chain (default true) extends the '
            "fillet along tangentially connected edges. One fillet feature is created for the whole edge set."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Fillet definition; edges and radius are required.",
            "properties": {
                "edges": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Stored selection handles of the edges to fillet, e.g. ["$selection_0"].',
                    "examples": [["$selection_0", "$selection_1"]],
                },
                "radius": {
                    "type": ["string", "number"],
                    "description": (
                        "Fillet radius as a Fusion expression, or a bare number in this "
                        "tool's units (default cm)."
                    ),
                    "examples": ["5 mm", "0.25 in"],
                },
                "is_tangent_chain": {
                    "type": "boolean",
                    "description": "Also fillet edges tangentially connected to the input edges (default: true).",
                },
                "units": UNITS_PROPERTY,
            },
            "required": ["edges", "radius"],
        },
    },
    {
        "name": CHAMFER,
        "category": CATEGORY_FEATURES,
        "description": (
            "Add an equal-distance chamfer across one or more edges of the active design. "
            "Edges are addressed by stored selection handle ($selection_0 from get_active_selection); "
            'distance is a Fusion expression such as "2 mm" and offsets both sides of the edge equally.'
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Chamfer definition; edges and distance are required.",
            "properties": {
                "edges": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Stored selection handles of the edges to chamfer, e.g. ["$selection_0"].',
                    "examples": [["$selection_0"]],
                },
                "distance": {
                    "type": ["string", "number"],
                    "description": (
                        "Chamfer offset distance as a Fusion expression, or a bare "
                        "number in this tool's units (default cm); offsets both sides equally."
                    ),
                    "examples": ["2 mm", "0.1 in"],
                },
                "units": UNITS_PROPERTY,
            },
            "required": ["edges", "distance"],
        },
    },
    {
        "name": HOLE,
        "category": CATEGORY_FEATURES,
        "description": (
            "Drill a simple hole at a point on a planar face of the active design. "
            "The face and its positioning point place the hole; diameter is a Fusion expression. "
            "Extent is a distance (needs a depth) or through-all, and direction picks which way the hole "
            "runs off the face normal. The face must be planar."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Hole definition; face, position, and diameter are required.",
            "properties": {
                "face": {
                    "type": "string",
                    "description": "Stored selection handle of the planar face the hole starts on.",
                    "examples": ["$selection_0"],
                },
                "position": {
                    "type": "object",
                    "description": "Hole centre as a 3D point in centimetres, dropped onto the face along its normal.",
                    "properties": {
                        "x": {
                            "type": ["string", "number"],
                            "description": (
                                "X coordinate; a bare number is this tool's "
                                "units (default cm), or a Fusion expression."
                            ),
                        },
                        "y": {
                            "type": ["string", "number"],
                            "description": (
                                "Y coordinate; a bare number is this tool's "
                                "units (default cm), or a Fusion expression."
                            ),
                        },
                        "z": {
                            "type": ["string", "number"],
                            "description": (
                                "Z coordinate; a bare number is this tool's "
                                "units (default cm), or a Fusion expression."
                            ),
                        },
                    },

                    "required": ["x", "y", "z"],
                    "additionalProperties": False,
                },
                "diameter": {
                    "type": ["string", "number"],
                    "description": (
                        "Hole diameter as a Fusion expression, or a bare "
                        "number in this tool's units (default cm)."
                    ),
                    "examples": ["8 mm", "0.25 in"],
                },
                "extent": {
                    "type": "string",
                    "enum": ["distance", "through_all"],
                    "description": "Hole extent: a fixed distance (needs depth) or through-all (default: distance).",
                },
                "depth": {
                    "type": ["string", "number"],
                    "description": (
                        "Hole depth as a Fusion expression, or a bare number in "
                        "this tool's units (default cm); required for extent=distance, "
                        "else ignored."
                    ),
                    "examples": ["10 mm"],
                },
                "direction": {
                    "type": "string",
                    "enum": ["positive", "negative"],
                    "description": "Which way the hole runs off the face normal (default: positive).",
                },
                "units": UNITS_PROPERTY,
            },
            "required": ["face", "position", "diameter"],
        },
    },
    {
        "name": RECTANGULAR_PATTERN,
        "category": CATEGORY_FEATURES,
        "description": (
            "Pattern bodies, faces, or features along one direction, optionally a second. "
            "Entities are addressed by stored selection handle and must all be the same kind. "
            "Each direction takes a linear edge or axis handle, an instance count, and a spacing expression. "
            "A second direction needs all three of its arguments."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Rectangular pattern; entities, direction_one, quantity_one, distance_one required.",
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Stored selection handles of the entities to pattern; all must be the same type.",
                    "examples": [["$selection_0"]],
                },
                "direction_one": {
                    "type": "string",
                    "description": "Stored selection handle of the linear edge or axis defining the first direction.",
                    "examples": ["$selection_1"],
                },
                "quantity_one": {
                    "type": "number",
                    "description": "Number of instances in the first direction, a unitless count.",
                    "examples": [3],
                },
                "distance_one": {
                    "type": ["string", "number"],
                    "description": (
                        "First-direction spacing as a Fusion expression, or a bare "
                        "number in this tool's units (default cm)."
                    ),
                    "examples": ["20 mm"],
                },
                "direction_two": {
                    "type": "string",
                    "description": "Optional handle of the edge or axis defining the second direction.",
                    "examples": ["$selection_2"],
                },
                "quantity_two": {
                    "type": "number",
                    "description": "Optional instance count in the second direction, a unitless count.",
                    "examples": [2],
                },
                "distance_two": {
                    "type": ["string", "number"],
                    "description": (
                        "Second-direction spacing as a Fusion expression, or a bare "
                        "number in this tool's units (default cm)."
                    ),
                    "examples": ["15 mm"],
                },
                "is_symmetric": {
                    "type": "boolean",
                    "description": "Distribute instances symmetrically about the seed (default: false).",
                },
                "units": UNITS_PROPERTY,
            },
            "required": ["entities", "direction_one", "quantity_one", "distance_one"],
        },
    },
    {
        "name": CIRCULAR_PATTERN,
        "category": CATEGORY_FEATURES,
        "description": (
            "Pattern bodies, faces, or features around an axis through a total angle. "
            "Entities are addressed by stored selection handle and must all be the same kind. "
            "The axis is a linear edge, construction axis, or cylindrical face handle; "
            "the angle defaults to a full circle."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Circular pattern definition; entities, axis, and quantity are required.",
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Stored selection handles of the entities to pattern; all must be the same type.",
                    "examples": [["$selection_0"]],
                },
                "axis": {
                    "type": "string",
                    "description": "Handle of the linear edge, axis, or cylindrical face defining the rotation axis.",
                    "examples": ["$selection_1"],
                },
                "quantity": {
                    "type": "number",
                    "description": "Number of instances around the axis, a unitless count.",
                    "examples": [6],
                },
                "total_angle": {
                    "type": "string",
                    "description": "Total sweep as a Fusion angle expression; a bare number is degrees.",
                    "examples": ["360 deg", "180 deg"],
                },
                "is_symmetric": {
                    "type": "boolean",
                    "description": "Distribute instances symmetrically about the seed (default: false).",
                },
            },
            "required": ["entities", "axis", "quantity"],
        },
    },
    {
        "name": CREATE_SKETCH,
        "category": CATEGORY_FEATURES,
        "description": (
            "Draw one or more curves on a base construction plane (xy, xz, or yz) of the "
            "root component. Each curve is a line between two points, a circle about a "
            "centre and radius, or an arc about a centre from a start point through a sweep; "
            "all coordinates and radii are in centimetres and arc sweeps are in degrees "
            "(counter-clockwise positive). Returns the sketch handle plus one handle per "
            "closed profile Fusion derived from the curves ($profile_0, ...); profiles are "
            "populated automatically, and an open curve chain yields none. Give a profile "
            "handle to extrude or revolve to make solid geometry."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Sketch definition; plane and a non-empty curves array are required.",
            "properties": {
                "plane": {
                    "type": "string",
                    "enum": SKETCH_PLANES,
                    "description": "Base construction plane the sketch lies on.",
                    "examples": ["xy"],
                },
                "curves": {
                    "type": "array",
                    "items": CURVE_SCHEMA,
                    "description": (
                        "Curves to draw, in centimetres. Endpoints that coincide chain into "
                        "closed profiles, so the order of curves does not matter."
                    ),
                    "examples": [
                        [
                            {"kind": "line", "start": {"x": 0, "y": 0, "z": 0}, "end": {"x": 2, "y": 0, "z": 0}},
                            {"kind": "line", "start": {"x": 2, "y": 0, "z": 0}, "end": {"x": 2, "y": 2, "z": 0}},
                            {"kind": "line", "start": {"x": 2, "y": 2, "z": 0}, "end": {"x": 0, "y": 2, "z": 0}},
                            {"kind": "line", "start": {"x": 0, "y": 2, "z": 0}, "end": {"x": 0, "y": 0, "z": 0}},
                        ]
                    ],
                },
                "units": UNITS_PROPERTY,
            },
            "required": ["plane", "curves"],
        },
    },
    {
        "name": EXTRUDE,
        "category": CATEGORY_FEATURES,
        "description": (
            "Sweep a closed profile into a solid body. The profile is a handle returned by "
            "create_sketch ($profile_0). operation controls how the new geometry combines with "
            "existing bodies (new_body by default). extent is a fixed distance (needs the "
            "distance argument), through_all, or a symmetric sweep about the profile plane "
            "(also needs distance); direction applies to the one-sided extents. The created "
            "body is returned as a handle for appearance or selection tools."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Extrude definition; profile is required.",
            "properties": {
                "profile": {
                    "type": "string",
                    "description": "Handle of the closed profile to sweep, from create_sketch.",
                    "examples": ["$profile_0"],
                },
                "operation": {
                    "type": "string",
                    "enum": FEATURE_OPERATIONS,
                    "description": "How the extruded geometry combines with existing bodies (default: new_body).",
                },
                "extent": {
                    "type": "string",
                    "enum": EXTRUDE_EXTENTS,
                    "description": "Extrude extent: distance, through all geometry, or symmetric (default: distance).",
                },
                "distance": {
                    "type": ["string", "number"],
                    "description": (
                        "Extrude distance as a Fusion expression, or a bare number "
                        "in this tool's units (default cm). Required for extent distance "
                        "and symmetric."
                    ),
                    "examples": ["10 mm", "2.5 cm"],
                },
                "units": UNITS_PROPERTY,
                "direction": {
                    "type": "string",
                    "enum": DIRECTIONS,
                    "description": "Which way a one-sided extent runs off the profile (default: positive).",
                },
            },
            "required": ["profile"],
        },
    },
    {
        "name": REVOLVE,
        "category": CATEGORY_FEATURES,
        "description": (
            "Sweep a closed profile about an axis through an angle to make a solid body. The "
            "profile is a handle from create_sketch; the axis is a stored entity handle or one "
            "of the strings x, y, or z for the root component's construction axes. The angle is "
            "a Fusion angle expression and defaults to a full 360-degree turn. operation "
            "controls how the new geometry combines with existing bodies."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Revolve definition; profile and axis are required.",
            "properties": {
                "profile": {
                    "type": "string",
                    "description": "Handle of the closed profile to revolve, from create_sketch.",
                    "examples": ["$profile_0"],
                },
                "axis": {
                    "type": "string",
                    "description": "Stored entity handle of the axis, or x, y, or z for a construction axis.",
                    "examples": ["$selection_0", "y"],
                },
                "operation": {
                    "type": "string",
                    "enum": FEATURE_OPERATIONS,
                    "description": "How the revolved geometry combines with existing bodies (default: new_body).",
                },
                "angle": {
                    "type": "string",
                    "description": (
                        "Total sweep as a Fusion angle expression; a bare number is degrees (default: full circle)."
                    ),
                    "examples": ["360 deg", "180 deg"],
                },
            },
            "required": ["profile", "axis"],
        },
    },
    {
        "name": CREATE_COMPONENT,
        "category": CATEGORY_FEATURES,
        "description": (
            "Add a new component to the root component's assembly and name it. The component "
            "is created by adding an occurrence with an identity transform, then naming the "
            "component that occurrence owns; the returned component handle identifies it for "
            "later selection."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Component definition; name is required.",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the new component; must be unique enough for the caller to find later.",
                    "examples": ["Bracket"],
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": CREATE_BODY,
        "category": CATEGORY_FEATURES,
        "description": (
            "Add a primitive box, cylinder, or sphere body to the root component. Dimensions "
            "are in centimetres: a box needs length, width, and height; a cylinder needs "
            "radius and height; a sphere needs radius. A parametric design wraps the body in a "
            "base feature on the timeline, a direct design adds it directly. The returned body "
            "handle can be given to apply_appearance."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Body definition; shape and dimensions are required.",
            "properties": {
                "shape": {
                    "type": "string",
                    "enum": BODY_SHAPES,
                    "description": "Primitive shape to build.",
                    "examples": ["box"],
                },
                "dimensions": DIMENSIONS_SCHEMA,
                "name": {
                    "type": "string",
                    "description": "Optional body name; Fusion assigns one when omitted.",
                    "examples": ["Housing"],
                },
                "units": UNITS_PROPERTY,
            },
            "required": ["shape", "dimensions"],
        },
    },
    {
        "name": APPLY_APPEARANCE,
        "category": CATEGORY_FEATURES,
        "description": (
            "Assign an appearance from a material library to a body. The body is a stored "
            "handle (from create_body, extrude, or a selection); the appearance is named from "
            "the library, which defaults to the Fusion 360 Material Library. The appearance is "
            "copied into the design and assigned to the body."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Appearance assignment; body and appearance are required.",
            "properties": {
                "body": {
                    "type": "string",
                    "description": "Stored handle of the body to recolour.",
                    "examples": ["$body_0"],
                },
                "appearance": {
                    "type": "string",
                    "description": "Name of the appearance in the library.",
                    "examples": ["Steel", "Aluminum"],
                },
                "library": {
                    "type": "string",
                    "description": f"Material library for the appearance (default: {DEFAULT_APPEARANCE_LIBRARY}).",
                    "examples": [DEFAULT_APPEARANCE_LIBRARY],
                },
            },
            "required": ["body", "appearance"],
        },
    },
    {
        "name": LIST_BODIES,
        "category": CATEGORY_INSPECTION,
        "description": (
            "List every solid and surface body in the root component, read-only. Each entry "
            "reports name, is_solid, volume in cubic centimetres, area in square centimetres, "
            "the tight-fitting bounding box, and face and edge counts. A design with no bodies "
            "returns an empty list, not an error. Call this to learn what a design contains "
            "before changing anything."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "No arguments; every body in the root component is reported.",
            "properties": {},
        },
    },
    {
        "name": INSPECT_ENTITY,
        "category": CATEGORY_INSPECTION,
        "description": (
            "Report the geometry of one body, face, or edge by stored selection handle, "
            "read-only. The reported fields depend on the kind: a body reports volume, area, "
            "bounding box, and face and edge counts; a face reports area, centroid, bounding "
            "box, and surface kind (plane, cylinder, cone, sphere, torus, elliptical cylinder, "
            "elliptical cone, or nurbs); an edge reports length and bounding box. Use "
            "get_active_selection first to capture the handle."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Entity inspection; the stored handle of the body, face, or edge is required.",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "Stored selection handle of the body, face, or edge to inspect.",
                    "examples": ["$selection_0"],
                },
            },
            "required": ["entity"],
        },
    },
    {
        "name": LIST_FEATURES,
        "category": CATEGORY_INSPECTION,
        "description": (
            "List the design's timeline nodes, read-only: sketches, construction geometry, "
            "canvas and decal inserts, joints, PMI, and features alike, each with its kind. "
            "Every node reports name, timeline index, is_suppressed, a health label (healthy, "
            "warning, error, suppressed, rolled back, or unknown), and the message Fusion "
            "attaches to a warning or an error. A direct design has no timeline and reports an "
            "empty list."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "No arguments; every timeline node is reported.",
            "properties": {},
        },
    },
    {
        "name": MEASURE,
        "category": CATEGORY_INSPECTION,
        "description": (
            "Measure between two stored selection handles, read-only. Mode 'distance' (the "
            "default) reports the minimum gap in centimetres; mode 'angle' reports the value in "
            "radians and in degrees. The two modes accept different geometry: distance measures "
            "bodies, faces, edges, and points, while angle rejects bodies and curved faces and "
            "measures points, linear edges, axes, and planar faces -- an incompatible kind is "
            "reported as invalid_value rather than passed to the API."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "description": "Measurement; both entity handles are required, mode defaults to distance.",
            "properties": {
                "entity_one": {
                    "type": "string",
                    "description": "Stored selection handle of the first entity to measure.",
                    "examples": ["$selection_0"],
                },
                "entity_two": {
                    "type": "string",
                    "description": "Stored selection handle of the second entity to measure.",
                    "examples": ["$selection_1"],
                },
                "mode": {
                    "type": "string",
                    "enum": MEASURE_MODES,
                    "description": "What to measure: 'distance' for a minimum gap, 'angle' for a rotation.",
                    "examples": ["distance"],
                },
            },
            "required": ["entity_one", "entity_two"],
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
    fusion_diagnostics,
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
    fillet,
    chamfer,
    hole,
    rectangular_pattern,
    circular_pattern,
    create_sketch,
    extrude,
    revolve,
    create_component,
    create_body,
    apply_appearance,
    list_bodies,
    inspect_entity,
    list_features,
    measure,
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
        FUSION_DIAGNOSTICS: fusion_diagnostics,
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
        FILLET: fillet,
        CHAMFER: chamfer,
        HOLE: hole,
        RECTANGULAR_PATTERN: rectangular_pattern,
        CIRCULAR_PATTERN: circular_pattern,
        CREATE_SKETCH: create_sketch,
        EXTRUDE: extrude,
        REVOLVE: revolve,
        CREATE_COMPONENT: create_component,
        CREATE_BODY: create_body,
        APPLY_APPEARANCE: apply_appearance,
        LIST_BODIES: list_bodies,
        INSPECT_ENTITY: inspect_entity,
        LIST_FEATURES: list_features,
        MEASURE: measure,
    }
    if set(handlers) != _TOOL_NAMES:
        raise RuntimeError(f"Handler registry mismatch: {set(handlers) ^ _TOOL_NAMES}")
    return handlers
