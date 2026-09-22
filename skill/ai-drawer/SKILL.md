---
name: ai-drawer
description: Drive Autodesk Fusion 360 through the ai-drawer MCP surface — a curated 36-tool set for sketching, features, inspection, and viewport capture, with no code execution.
---

# ai-drawer — operating manual for the Fusion 360 surface

You are driving **Autodesk Fusion 360** through the `ai-drawer` suite. This file
is the manual for the surface: read it once, then work the loop below.

## What the suite is

Three parts, and none of them works alone:

1. **`ai-drawer-mcp`** — the npm package OpenCode launches as a stdio MCP server.
   It is the only thing you talk to.
2. **`AutodeskFusionMCP`** — a Python add-in running *inside* Fusion on the
   Windows host. It receives your tool calls and dispatches them onto the Fusion
   main thread.
3. **this skill** — the manual you are reading.

Between them they expose **36 tools** in **8 categories**: viewport (3),
selection (1), documents (7), parameters (3), features (11), inspection (4),
documentation (3), diagnostics (2). Two of those 36 are answered by the bridge
itself and never reach Fusion: `fusion_health` and `list_tool_categories`.

**The surface is curated and contains no code execution.** There is no
`execute_python`, no generic API caller, no script storage. You cannot make
Fusion run arbitrary code, and you should not try: names outside the curated set
are refused and logged. Work within the tools that exist.

## The canonical loop

Every non-trivial task follows this shape. Skip steps only when you already have
the answer from the previous turn.

1. **`list_tool_categories`** — what is available right now. Cheap, bridge-owned,
   takes no arguments. It lists the live tools by category, so it is also your
   ground truth when you are unsure what exists.
2. **`fusion_health`** — is the add-in alive? Reports `host`, `port`, `state`,
   `latency_ms`, `last_error`. If a tool call fails with anything
   connection-shaped, come back here before retrying anything.
3. **Plan** — decide the feature sequence before touching the model. Say the plan
   out loud in one or two lines: which plane, which dimensions, which order.
4. **Mutate** — sketch → extrude/revolve → fillet/chamfer/hole → pattern →
   component/body → appearance. One tool call per step (see the rules below).
5. **Verify** — `list_bodies`, `inspect_entity`, `list_features`, `measure`. Read
   the geometry back instead of assuming the mutation landed the way you meant.
6. **`capture_viewport`** — a PNG of the result. This is how you *see* the model.
   Use it generously; it costs one call and removes most guessing.

Verify before you capture, and capture before you declare done.

## Rule 1 — entities are addressed by stored selection handle

Geometry is not addressed by name, by ID, or by a token you invent. It is
addressed by **stored selection handle**, and there is exactly one way to get
one:

1. The user picks something in the viewport.
2. You call **`get_active_selection`**. It stores each picked entity in the
   shared object store and hands back handles like `$selection_0`,
   `$selection_1`, … in the `stored_as` field of each entry.
3. You pass those handles to the tool that needs them — `fillet` takes edge
   handles, `inspect_entity` takes one, `measure` takes two, and so on.

This is a **two-step round trip**, and it is the only addressing path that cannot
lie about what is selected: there is deliberately no reverse lookup from token to
object. Consequences worth remembering:

- **Handles are invalidated by the next `get_active_selection`** — it clears the
  previous selection entries from the store. Do not hoard handles across calls;
  use them in the turn you got them.
- **Order is the viewport's order**, index 0 first. If the user's selection
  changed between your call and the mutation, the handle may point at something
  else — verify with an inspection tool if it matters.
- If a tool needs an entity and the user has not selected one, ask the user to
  select it and call `get_active_selection` again. There is no way to address by
  name.

## Rule 2 — units

Three forms are accepted, and the distinction is per-argument:

- **Expression strings** — anything the Fusion expression engine takes:
  `"5 mm"`, `"360 deg"`, `"width/2"`. Use these whenever you want a unit the
  design understands, and prefer them for dimensions a human reads.
- **Bare numbers** — read in the call's unit, which is **centimetres unless the
  `units` field says otherwise**. `2.0` with no `units` means 2 cm.
- **The `units` field** — every dimension-bearing tool accepts an optional
  top-level `units` (`"mm"`, `"cm"`, `"in"`, `"m"`) that sets the unit for every
  bare number in that call. `units: "mm"` + `radius: 5` is 5 mm; without it, the
  same `5` is 5 cm. It never applies to expression strings — those carry their
  own unit and are passed to the engine unchanged.

Not every argument accepts both forms; the tool's own schema says which. When in
doubt, pass a string with an explicit unit — `"5 mm"` is unambiguous, `5` is not.

**This is the mistake that distorted a real model on the first field run.** The
user passed a bare `92` intending millimetres; the surface read it as internal
centimetres, so the part came out at 92 cm — an order of magnitude wrong, and
silent until the geometry was inspected. The rule: **pass an expression string
with an explicit unit for every dimension a human reads** (`"92 mm"`, `"5 mm"`),
or set `units: "mm"` once and use bare numbers for the whole call. Use bare
numbers with no `units` only when you genuinely mean internal centimetres.

Inspection results come back in the same system: distances and volumes in
centimetres, angles in radians. Convert before quoting a number to the user.

## Rule 3 — mutations are one-shot

**Every mutation is one-shot: a failure is reported once and never retried.**
This is deliberate — a half-applied feature is worse than a clean error, and a
blind retry can double-apply a fillet or drill a second hole.

So when a mutation fails:

- Do **not** retry the same call. Read the structured error instead: it carries a
  `kind`, a message written to be reasoned about, and often a `hint`.
- Fix the stated cause, then call again with corrected arguments.
- If the error is connection-shaped, go back to `fusion_health` before anything
  else.

Verification is cheap and retries are free; mutations are neither.

## Rule 4 — plane orientation

Fusion's base sketch planes have fixed normals, and the mapping is not
negotiable: **XY has normal Z, XZ has normal Y, YZ has normal X.** When you
sketch on XZ or YZ, the sketch's vertical maps to a world axis different from
the one you may intuit — and the direction can be the opposite of what you
assumed.

This is not a theoretical concern. In the field, reinforcing geometry sketched on
XZ went the wrong way: it built downward instead of upward, left the intended
reference, and produced **disconnected bodies**. That is a silent and expensive
failure — nothing errors out, and it only surfaces later when the model does not
come together.

The discipline:

- **Confirm the orientation before committing geometry.** Call `get_viewport`
  first — it is cheap, reports the camera — including its `up_vector` — and
  grounds your mental model of which way is up on the plane you are about to use.
- **Prefer sketching on XY and placing geometry by its coordinates** rather than
  reasoning about a rotated plane. XY's normal is world Z, which matches the
  intuition you build on paper; anything you want on another face can be reached
  by offsetting or extruding in a stated direction.
- **If a body lands disconnected or on the wrong side, suspect the plane before
  you suspect the dimensions.** A unit error (Rule 2) scales a part; a plane
  error puts it somewhere else entirely.

## Documents and models

A design must be open before any geometry call. If there is no active design you
get a `No active Fusion design; open or create a document first` error — fix it
with `new_document` or `open_document`, not by repeating the geometry call.
`list_documents` and `get_document_info` tell you what is open.

Designs come in two flavours, `parametric` and `direct`; the choice is an argument
on the creation tools, and it changes whether your features land on the timeline.
`list_features` reads that timeline (name, suppressed state, health), and
`list_parameters` / `modify_parameter` drive the parameters behind a parametric
model.

## Documentation is a tool

`fetch_api_documentation` and `fetch_online_documentation` search the Fusion API
— the same API surface you are operating through. When a tool's schema is not
enough to know what an argument means, search the API for the underlying class
rather than guessing. `fetch_design_guide` carries the bundled design guidance.

## Networking

If Fusion runs on the Windows host while you run in WSL, the bridge has to reach
it. That is a real problem with mode-dependent answers, and it is documented
properly in **[docs/WSL-NETWORKING.md](../../docs/WSL-NETWORKING.md)** — read it
when `fusion_health` reports it cannot connect. The short version: the add-in
binds `127.0.0.1:8765` by default; NAT-mode WSL needs a different bind on the
add-in side, and the bridge auto-detects the WSL gateway when nothing is
configured.

## What you cannot do

- **No drawings.** The drawing/sheet surface is not exposed. Do not plan a
  workflow that ends in a 2D drawing.
- **No code execution.** Not a limitation to work around — the surface is built
  this way.
- **No retroactive edits by name.** If the user wants an existing feature
  changed, the path is: select it, `get_active_selection`, inspect, then decide.
  Parameters are the one exception — `modify_parameter` edits by parameter name.

## Quick reference

| Need | Tool |
| --- | --- |
| What can I call? | `list_tool_categories` |
| Is Fusion alive? | `fusion_health` |
| What did the user pick? | `get_active_selection` → `$selection_N` |
| What is in the model? | `list_bodies`, `inspect_entity` |
| What is on the timeline? | `list_features` |
| How far apart are these? | `measure` |
| Make geometry | `create_sketch`, `extrude`, `revolve`, `create_body`, `create_component` |
| Detail and repeat | `fillet`, `chamfer`, `hole`, `rectangular_pattern`, `circular_pattern`, `apply_appearance` |
| See it | `capture_viewport` |
| Which way is up? | `get_viewport` before sketching on XZ/YZ |
| Look something up | `fetch_api_documentation`, `fetch_online_documentation`, `fetch_design_guide` |
