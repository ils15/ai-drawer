# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) as far as
alpha software can: during `0.1.0-alpha.*`, tool additions and behaviour changes
land without a bump, because nothing is stable yet.

## [0.1.0-alpha.1]

The first tagged cut of the suite: a curated 36-tool surface over Fusion 360,
with no arbitrary code execution anywhere in it.

### What works

- **36 tools, 8 categories.** The add-in serves 34 — viewport (3), selection (1),
  documents (7), parameters (3), features (11), inspection (4), documentation
  (3), diagnostics (2) — and the bridge answers two itself: `fusion_health` and
  `list_tool_categories`. `list_tool_categories` publishes exactly that
  grouping, and nothing more, at call time.
- **A complete text-to-CAD loop.** Sketch on a base plane, extrude or revolve,
  fillet, chamfer, drill, pattern, wrap in a component or a primitive body,
  apply an appearance, then verify with `list_bodies`, `inspect_entity`,
  `list_features`, and `measure`, and see the result with `capture_viewport`.
- **Read-only inspection.** Body inventory with volume, area, bounding box, face
  and edge counts; per-entity geometry (face surface kind, edge length);
  timeline health; minimum-distance and angle measurement between stored
  entities.
- **Structured errors.** Every failure comes back as a typed envelope with a
  kind, a message written to be reasoned about, and a hint. No tracebacks, no
  silent `null`.
- **Documents and parameters.** Create, open, save, export (STEP, STL, F3D,
  IGES, OBJ, PDF), and close documents; read and edit the user parameters that
  drive a parametric model.
- **Curated security.** Named, capability-oriented tools with fixed schemas.
  `execute_python`, the generic API caller, and the script storage tools do not
  exist in this build; the bridge additionally refuses and logs any name outside
  its allowlist, so an add-in that advertised them could not widen the surface.
- **Two-party transport.** A stdio MCP server (`ai-drawer-mcp`) that OpenCode
  launches, talking Streamable HTTP to the add-in inside Fusion; every `adsk.*`
  call is dispatched onto the Fusion main thread.
- **Test suite.** 394 pytest tests pass on the add-in side with the Fusion API
  mocked, and 122 bridge tests pass. The cross-package drift guard pins the two
  sides of the surface together so they cannot drift silently — it is the one
  suite member still red on this cut, because the bridge-side mirror of the new
  inspection category has not been regenerated yet. That lands before tagging.
- **Skills integration.** The `ai-drawer` skill gives the LLM the operating
  manual for the surface above.

### What does not work

- **Drawings.** The drawing/sheet API surface is not exposed, so no creating or
  editing 2D drawings through this suite.
- **No arbitrary code execution, by design.** If you need to run a script inside
  Fusion, this suite will not do it, and that is not going to change in the
  `0.1.0` line.
- **Verification is partial.** The viewport, selection, and documentation tools
  have been exercised against a real Fusion 360 on Windows. The newer groups are
  covered by the mocked test suite and by a smoke harness
  (`packages/addin/tests/smoke/`) that has not yet been run over the full
  surface.

### Alpha caveats

- The tool surface is not frozen. Names, schemas, and return shapes can change
  before `0.1.0`.
- The HTTP endpoint is unauthenticated and binds to loopback by default.
  Non-loopback binding is supported (it is required for NAT-mode WSL) and is
  your responsibility to scope — see [docs/WSL-NETWORKING.md](docs/WSL-NETWORKING.md).
- Documents this applies to: [README](README.md), [docs/INSTALL.md](docs/INSTALL.md),
  [docs/COEXISTENCE.md](docs/COEXISTENCE.md), [docs/UPSTREAM-MERGE.md](docs/UPSTREAM-MERGE.md).
- Provenance: the add-in is a derivative of Frank Hommers' MIT-licensed
  `autodesk-fusion-mcp` (v1.4.1). The inherited surface is 7 tools; the other 27
  are ours. See [docs/UPSTREAM-MERGE.md](docs/UPSTREAM-MERGE.md) for the record.
