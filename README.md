# ai-drawer

## Status: alpha

Early, usable for what it does today, and honest about what it does not do.

`ai-drawer` connects an LLM running in [OpenCode](https://opencode.ai/) to
Autodesk Fusion 360 over the Model Context Protocol. The architecture is a
two-party pipeline: a TypeScript bridge (`packages/bridge`, stdio MCP →
Streamable HTTP) talks to a Python add-in (`packages/addin`) that runs *inside*
Fusion and dispatches every `adsk.*` call onto the Fusion main thread.

**What works today:** inspecting and driving an open Fusion document through a
curated surface of **19 safe tools**: 18 add-in tools plus the local
`fusion_health` probe.

The add-in tools are grouped as follows:

- **Inherited viewport/selection/docs:** `capture_viewport`, `get_viewport`,
  `set_viewport`, `get_active_selection`, `fetch_api_documentation`,
  `fetch_online_documentation`, `fetch_design_guide`
- **Lifecycle/documents:** `fusion_status`, `new_document`, `open_document`,
  `close_document`, `save_document`, `export_document`, `list_documents`,
  `get_document_info`
- **Parameters:** `add_parameter`, `list_parameters`, `modify_parameter`

Wave-3 tools are not exposed yet.

**What does not work yet: creating CAD geometry from natural language.** CAD
geometry tools are not shipped yet. The next phase adds sketch and feature
tools; meanwhile, a smoke-test harness exercises the real Fusion integration
([smoke-test docs](packages/addin/tests/smoke/README.md)).

We would rather you know that now than discover it after installing.

## Install

Full instructions, with a "which setup am I?" table and a troubleshooting guide:

**→ [docs/INSTALL.md](docs/INSTALL.md)**

The short version for the common case (OpenCode in WSL, Fusion on the Windows
host): copy `packages/addin` to
`%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\` as `AutodeskFusionMCP`,
Shift+S → Add-Ins → Run, build `packages/bridge`, and register the stdio server
in OpenCode. WSL networking has one wrinkle worth understanding — see
[docs/WSL-NETWORKING.md](docs/WSL-NETWORKING.md).

## Security

The tool surface is **curated, and deliberately has no arbitrary code execution**.
`execute_python` is not exposed, and neither are generic API callers or
user-script storage tools. The available tools are named, capability-oriented,
and use fixed schemas; an LLM can drive Fusion through them but cannot make
Fusion run arbitrary code.

The HTTP endpoint itself is unauthenticated and binds to loopback
(`127.0.0.1:8765`) by default. Non-loopback binding is possible — necessary for
NAT-mode WSL — and it is your responsibility to scope it. See
[docs/WSL-NETWORKING.md §Security note](docs/WSL-NETWORKING.md#security-note).

## Attribution and license

MIT. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).

The add-in is a derivative of **Frank Hommers'** MIT-licensed
[`autodesk-fusion-mcp`](https://github.com/frankhommers/autodesk-fusion-mcp)
(v1.4.1); upstream commits retain their original authorship. The upstream sync
procedure is documented in [docs/UPSTREAM-MERGE.md](docs/UPSTREAM-MERGE.md).

## Repository layout

| Path | Owner | Purpose |
| --- | --- | --- |
| `packages/addin/` | this project | Python add-in running inside Fusion 360 |
| `packages/bridge/` | separate workstream | TypeScript stdio→HTTP bridge (client side) |

## Development

```bash
# Python add-in tests (no Fusion required; adsk is mocked in the test bootstrap)
cd packages/addin
python -m unittest discover -s tests

# Lint
ruff check .
```

```bash
# Bridge
cd packages/bridge
npm run test     # vitest run
npm run lint     # biome check src tests
npm run build    # tsc → dist/
```

The bridge requires Node 20 or newer.
