# ai-drawer

## Status: alpha

Early, usable for what it does today, and honest about what it does not do.

`ai-drawer` connects an LLM running in [OpenCode](https://opencode.ai/) to
Autodesk Fusion 360 over the Model Context Protocol. It is a suite of three
parts that only work together:

- **`ai-drawer-mcp`** — the npm package at `packages/bridge`: a TypeScript stdio
  MCP server that OpenCode launches, and a Streamable HTTP client that talks to
  the add-in.
- **`AutodeskFusionMCP`** — the Python add-in at `packages/addin`, which runs
  *inside* Fusion and dispatches every `adsk.*` call onto the Fusion main thread.
- **the `ai-drawer` skill** — the operating manual at `skill/ai-drawer/` that the
  LLM reads, so it drives Fusion the way the surface wants to be driven.

## What works today

Inspecting and driving an open Fusion document through a curated surface of
**36 tools**: 34 served by the add-in, plus two the bridge answers itself
(`fusion_health`, `list_tool_categories`). The add-in groups its 34 into eight
categories:

- **viewport** (3) — `capture_viewport`, `get_viewport`, `set_viewport`
- **selection** (1) — `get_active_selection`
- **documents** (7) — `list_documents`, `new_document`, `open_document`,
  `save_document`, `export_document`, `close_document`, `get_document_info`
- **parameters** (3) — `add_parameter`, `list_parameters`, `modify_parameter`
- **features** (11) — `create_sketch`, `extrude`, `revolve`, `create_component`,
  `create_body`, `apply_appearance`, `fillet`, `chamfer`, `hole`,
  `rectangular_pattern`, `circular_pattern`
- **inspection** (4) — `list_bodies`, `inspect_entity`, `list_features`,
  `measure`
- **documentation** (3) — `fetch_api_documentation`, `fetch_online_documentation`,
  `fetch_design_guide`
- **diagnostics** (2) — `fusion_status`, `fusion_diagnostics`

The two bridge-owned helpers are classified under diagnostics: `fusion_health`
probes the add-in on demand, and `list_tool_categories` publishes the grouping
above. Neither is ever forwarded to Fusion.

That surface supports a complete text-to-CAD loop: sketch, extrude or revolve,
fillet, pattern, apply an appearance, then inspect the result (`list_bodies`,
`inspect_entity`, `list_features`, `measure`) and capture the viewport to see
it. The LLM-facing playbook for that loop is
[`skill/ai-drawer/SKILL.md`](skill/ai-drawer/SKILL.md).

## What does not work yet

- **Drawings.** The drawing/sheet API surface is not exposed. There is no way to
  create or edit a 2D drawing through this suite — not today, and not on the
  near-term roadmap.
- **Nothing else is hidden behind a curtain.** The list above is the whole
  surface; `list_tool_categories` reports exactly those tools and nothing more.

**Verification status.** The viewport, selection, and documentation tools have
been exercised against a real Fusion 360 on Windows. The newer groups are
covered by the automated suite (mocked Fusion) and by a smoke harness that runs
against a real Fusion but has not yet been run over the full surface:
[`packages/addin/tests/smoke/`](packages/addin/tests/smoke/README.md). Treat the
alpha accordingly.

## Install

Full instructions, with a "which setup am I?" table and a troubleshooting guide:

**→ [docs/INSTALL.md](docs/INSTALL.md)**

The short version for the common case (OpenCode in WSL, Fusion on the Windows
host): copy `packages/addin` to
`%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\` as `AutodeskFusionMCP`,
Shift+S → Add-Ins → Run, build `packages/bridge`, and register the stdio server
in OpenCode. WSL networking has one wrinkle worth understanding — see
[docs/WSL-NETWORKING.md](docs/WSL-NETWORKING.md).

If you already run Frank Hommers' `autodesk-fusion-mcp` add-in, both default to
the same port; see [docs/COEXISTENCE.md](docs/COEXISTENCE.md).

## Security

The tool surface is **curated, and deliberately has no arbitrary code
execution**. There is no `execute_python`, no generic API caller, and no
user-script storage. The available tools are named, capability-oriented, and use
fixed schemas; an LLM can drive Fusion through them but cannot make Fusion run
arbitrary code. Names outside the curated set are refused and logged, even if
the add-in advertised them.

The HTTP endpoint itself is unauthenticated and binds to loopback
(`127.0.0.1:8765`) by default. Non-loopback binding is possible — necessary for
NAT-mode WSL — and it is your responsibility to scope it. See
[docs/WSL-NETWORKING.md §Security note](docs/WSL-NETWORKING.md#security-note).

## Attribution and license

MIT. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).

The add-in is a derivative of **Frank Hommers'** MIT-licensed
[`autodesk-fusion-mcp`](https://github.com/frankhommers/autodesk-fusion-mcp)
(v1.4.1); upstream commits retain their original authorship. The upstream sync
procedure and the record of deliberate divergence live in
[docs/UPSTREAM-MERGE.md](docs/UPSTREAM-MERGE.md); how to run both add-ins
side by side is in [docs/COEXISTENCE.md](docs/COEXISTENCE.md).

## Repository layout

| Path | Purpose |
| --- | --- |
| `packages/bridge/` | TypeScript stdio→HTTP bridge, published as `ai-drawer-mcp` |
| `packages/addin/` | Python add-in running inside Fusion 360 as `AutodeskFusionMCP` |
| `skill/ai-drawer/` | the OpenCode skill the LLM reads |
| `docs/` | install, WSL networking, upstream sync, coexistence |

## Development

```bash
# Python add-in tests (no Fusion required; adsk is mocked in the test bootstrap)
cd packages/addin
python3 -m pytest        # the suite uses pytest markers; unittest cannot import it
python3 -m ruff check .
```

```bash
# Bridge
cd packages/bridge
npm run test     # vitest run
npm run lint     # biome check src tests
npm run build    # tsc → dist/
```

The bridge requires Node 20 or newer. Changes to the tool surface on either side
are pinned together by a cross-package drift guard
(`packages/bridge/tests/drift-guard.test.ts`), so the two cannot drift apart
silently.

## Changes

See [CHANGELOG.md](CHANGELOG.md).
