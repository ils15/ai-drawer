# ai-drawer

**Status: WIP** — this project is an early-stage work in progress and is not
usable yet.

`ai-drawer` is an MCP (Model Context Protocol) server that connects an LLM
running in WSL (via OpenCode) to Autodesk Fusion 360 running on the Windows
host, so CAD geometry can be created from natural-language prompts. The
architecture is a two-party pipeline: a TypeScript npm bridge package
(`packages/bridge`, stdio MCP in WSL → Streamable HTTP) talks to a Python
add-in (`packages/addin`) that runs *inside* Fusion and dispatches every
`adsk.*` call onto the Fusion main thread.

The add-in is a derivative of Frank Hommers' MIT-licensed
`autodesk-fusion-mcp` (v1.4.1); see [NOTICE.md](NOTICE.md) for attribution and
[docs/UPSTREAM-MERGE.md](docs/UPSTREAM-MERGE.md) for the upstream sync
procedure.

## Repository layout

| Path | Owner | Purpose |
| --- | --- | --- |
| `packages/addin/` | this project | Python add-in running inside Fusion 360 |
| `packages/bridge/` | separate workstream | TypeScript stdio→HTTP bridge (WSL side) |

## Development

```bash
# Python add-in tests (no Fusion required; adsk is mocked in the test bootstrap)
cd packages/addin
python -m unittest discover -s tests

# Lint
ruff check .
```
