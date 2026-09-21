# ai-drawer-mcp

A TypeScript stdio MCP server that an MCP client (e.g. [OpenCode](https://opencode.ai/))
launches, and a Streamable HTTP client that talks to the `AutodeskFusionMCP` add-in running
inside Autodesk Fusion 360.

## Status: alpha

Early, usable for what it does today, and honest about what it does not do.

## What this is — and what it needs

**This package is one of three parts, and it is useless on its own.** It speaks stdio to an LLM
client and HTTP to the add-in; it cannot reach Fusion by itself, so every tool call fails with
a connection error until the Python add-in is running inside Fusion 360. That is expected, not
a bug to file.

1. **`ai-drawer-mcp`** — this package, the stdio→HTTP bridge.
2. **`AutodeskFusionMCP`** — the Python add-in at
   [`packages/addin`](https://github.com/ils15/ai-drawer/blob/main/packages/addin), which runs
   *inside* Fusion and dispatches every `adsk.*` call onto the Fusion main thread.
3. **the `ai-drawer` skill** — the LLM-facing playbook at
   [`skill/ai-drawer/SKILL.md`](https://github.com/ils15/ai-drawer/blob/main/skill/ai-drawer/SKILL.md).

The curated surface is **36 tools**: 34 served by the add-in across eight categories, plus two
the bridge answers itself (`fusion_health`, `list_tool_categories`). Neither of those two is
ever forwarded to Fusion.

- **viewport** (3) — `capture_viewport`, `get_viewport`, `set_viewport`
- **selection** (1) — `get_active_selection`
- **documents** (7) — `list_documents`, `new_document`, `open_document`, `save_document`,
  `export_document`, `close_document`, `get_document_info`
- **parameters** (3) — `add_parameter`, `list_parameters`, `modify_parameter`
- **features** (11) — `create_sketch`, `extrude`, `revolve`, `create_component`, `create_body`,
  `apply_appearance`, `fillet`, `chamfer`, `hole`, `rectangular_pattern`, `circular_pattern`
- **inspection** (4) — `list_bodies`, `inspect_entity`, `list_features`, `measure`
- **documentation** (3) — `fetch_api_documentation`, `fetch_online_documentation`,
  `fetch_design_guide`
- **diagnostics** (2) — `fusion_status`, `fusion_diagnostics`

That surface supports a complete text-to-CAD loop: sketch, extrude or revolve, fillet, pattern,
apply an appearance, inspect the result, and capture the viewport. Drawings are not exposed, and
nothing else is hidden behind a curtain — `list_tool_categories` reports exactly the tools above.

## Install

Requires Node 20 or newer.

```bash
npm install -g ai-drawer-mcp@alpha   # or, without installing: npx ai-drawer-mcp
```

Then install the add-in — mandatory, not optional. Copy
[`packages/addin`](https://github.com/ils15/ai-drawer/blob/main/packages/addin) to
`%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\` as `AutodeskFusionMCP`, and run it in Fusion
via Shift+S → Add-Ins → Run. Full instructions, with a "which setup am I?" table and a
troubleshooting guide:
[docs/INSTALL.md](https://github.com/ils15/ai-drawer/blob/main/docs/INSTALL.md).

## Configuration

The bridge connects to the add-in over HTTP. Resolution order:

1. `FUSION_MCP_HOST` / `FUSION_MCP_PORT` — explicit values win.
2. Default `127.0.0.1:8765`.
3. Under WSL only, if `127.0.0.1` refuses, resolve the Windows host gateway from
   `ip route show default` and/or the first nameserver in `/etc/resolv.conf`, then cache
   whichever host actually answers for the lifetime of the process.

An explicitly configured host is never second-guessed: if it does not answer, the error text
names exactly what you configured.

## Security

The tool surface is curated, and deliberately has **no arbitrary code execution**. There is no
`execute_python`, no generic API caller, and no user-script storage. The tools are named,
capability-oriented, and use fixed schemas; an LLM can drive Fusion through them but cannot
make Fusion run arbitrary code. Names outside the curated set are refused and logged, even if
the add-in advertised them.

The HTTP endpoint is unauthenticated and binds to loopback (`127.0.0.1:8765`) by default.
Non-loopback binding is possible — necessary for NAT-mode WSL — and it is your responsibility to
scope it (see [docs/WSL-NETWORKING.md](https://github.com/ils15/ai-drawer/blob/main/docs/WSL-NETWORKING.md)).

## License and attribution

MIT. See [LICENSE](https://github.com/ils15/ai-drawer/blob/main/LICENSE) and
[NOTICE.md](https://github.com/ils15/ai-drawer/blob/main/NOTICE.md).

This project is a derivative of **Frank Hommers'** MIT-licensed
[`autodesk-fusion-mcp`](https://github.com/frankhommers/autodesk-fusion-mcp) (v1.4.1); upstream
commits retain their original authorship.
