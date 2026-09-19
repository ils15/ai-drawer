# ai-drawer

## Status: alpha

Early, usable for what it does today, and honest about what it does not do.

`ai-drawer` connects an LLM running in [OpenCode](https://opencode.ai/) to
Autodesk Fusion 360 over the Model Context Protocol. The architecture is a
two-party pipeline: a TypeScript bridge (`packages/bridge`, stdio MCP →
Streamable HTTP) talks to a Python add-in (`packages/addin`) that runs *inside*
Fusion and dispatches every `adsk.*` call onto the Fusion main thread.

**What works today:** inspecting and driving an open Fusion document — viewport
capture and control, active selection, and documentation lookup. Seven tools.

**What does not work yet: creating CAD geometry from natural language.** That is
the point of the project, and it is not there. Geometry creation is a later wave;
until then the tool surface is intentionally small and curated. If you are here
for "describe a part and get CAD," this project is not ready for you yet. Track
progress in [docs/drawing-api-status.md](docs/drawing-api-status.md) (coming
later).

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
This build removed the upstream tools that made it possible:

- `execute_python` — arbitrary Python execution inside Fusion (an RCE vector)
- `call_autodesk_api` — a generic dotted-path API caller
- the user-script store (`save_script`, `load_script`, `list_scripts`,
  `delete_scripts`)

What remains is a small set of named, capability-oriented tools, each with a
fixed schema. An LLM can drive Fusion through those tools; it cannot make Fusion
run arbitrary code.

The HTTP endpoint itself is unauthenticated and binds to loopback
(`127.0.0.1:8765`) by default. Non-loopback binding is possible — necessary for
NAT-mode WSL — and it is your responsibility to scope it. See
[docs/WSL-NETWORKING.md §Security note](docs/WSL-NETWORKING.md#security-note).

## Attribution and license

MIT. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).

The add-in is a derivative of **Frank Hommers'** MIT-licensed
[`autodesk-fusion-mcp`](https://github.com/frankhommers/autodesk-fusion-mcp)
(v1.4.1); upstream commits retain their original authorship. The upstream sync
procedure — including the one merge command that works and the one that silently
drops files — is in [docs/UPSTREAM-MERGE.md](docs/UPSTREAM-MERGE.md).

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
