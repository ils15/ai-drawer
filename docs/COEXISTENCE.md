# Coexistence — running this add-in next to the upstream one

`ai-drawer`'s add-in is a derivative of Frank Hommers'
[`autodesk-fusion-mcp`](https://github.com/frankhommers/autodesk-fusion-mcp)
(see [UPSTREAM-MERGE.md](UPSTREAM-MERGE.md) for what that means and how syncing
works). If you already run the upstream add-in, the two can live on the same
machine — but not on the same port, and not in the same folder name.

---

## The port conflict

Both add-ins bind `127.0.0.1:8765` by default. Only one can own that socket.

**Neither project changes its default.** 8765 is what every install guide, error
message, and smoke test assumes, so moving it would break the common path for
everyone who runs just one of them. Instead, move the one you use less. The
knobs are on opposite ends of the wire:

| Side | Knob | Where | Default |
| --- | --- | --- | --- |
| **add-in** (binds) | `MCP_SERVER_HOST` / `MCP_SERVER_PORT` | [`packages/addin/settings.py`](../packages/addin/settings.py) | `127.0.0.1` / `8765` |
| **bridge** (connects) | `FUSION_MCP_HOST` / `FUSION_MCP_PORT` | environment variables of the OpenCode process | unset → `127.0.0.1` / `8765` |

Keep the pair in sync: if you move the add-in to `8766`, the bridge that talks
to it needs `FUSION_MCP_PORT=8766`. The bridge resolving to a different add-in
than the one you meant is the one real failure mode here, and `fusion_health`
reports the `host` and `port` it actually resolved, so call it first when
anything looks wrong.

Two independent bridges in one OpenCode config is fine — register each with its
own `FUSION_MCP_PORT` and they never interfere:

```json
{
  "mcpServers": {
    "ai-drawer": {
      "type": "local",
      "command": ["node", "/path/to/ai-drawer/packages/bridge/dist/bin.js"],
      "enabled": true
    },
    "upstream-fusion": {
      "type": "local",
      "command": ["node", "/path/to/upstream-bridge/dist/bin.js"],
      "enabled": true,
      "env": { "FUSION_MCP_PORT": "8766" }
    }
  }
}
```

(In that example the upstream add-in is the one moved to 8766; swap the `env`
block if you move ours instead.)

---

## The folder conflict

Fusion identifies add-ins by folder name, and both projects ship a folder called
`AutodeskFusionMCP`. Two folders with the same name cannot sit in
`%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\`.

**Ours keeps the name; rename the upstream copy.** This is deliberate, not
arbitrary: the folder name is baked into the upstream sync procedure and into
every error message the bridge emits (see
[UPSTREAM-MERGE.md](UPSTREAM-MERGE.md)), so renaming ours would break `git
subtree pull` and make the troubleshooting text in
[INSTALL.md](INSTALL.md) lie. The upstream folder has no such constraint on our
side — renaming it costs nothing but a one-line edit to its own config, and it
is the upstream project's own convention to rename per install.

So:

```
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\
├── AutodeskFusionMCP\        ← ours, name is load-bearing
└── frankhommers-fusion-mcp\  ← upstream, renamed
```

If the upstream add-in resolves its own port from its own settings the same way,
point it at 8766 there; otherwise whatever mechanism that release uses for port
configuration applies, and this document cannot prescribe it — check that
project's docs.

---

## What diverged, in one place

The short version; the authoritative record is
[UPSTREAM-MERGE.md](UPSTREAM-MERGE.md).

**Removed.** Six raw-capability tools that would have made the bridge an
arbitrary-code-execution channel: `execute_python`, `call_autodesk_api`,
`save_script`, `load_script`, `list_scripts`, `delete_scripts`. They are not
merely disabled — the modules behind them are deleted, and
`tests/test_removed_tools.py` fails if a future upstream merge resurrects them.

**Added.** Five groups that upstream does not have, all ours: documents (7),
parameters (3), diagnostics (2), features (11), and read-only inspection (4).
That is 27 tools on top of the 7 inherited, 34 served by the add-in, 36 with the
two bridge-owned helpers. See [README](../README.md#what-works-today) for the
full surface.

**Kept compatible.** The inherited 7 tools behave as upstream ships them; the
HTTP protocol, the loopback default, and the add-in folder name are unchanged.

---

## Which one is answering?

If a tool call behaves in a way that does not match the docs you are reading,
confirm which add-in the bridge actually reached — `fusion_health` reports the
endpoint plus add-in state, and `list_tool_categories` reports our eight
categories with the live tool names. The upstream surface has neither, so the
shape of the answer tells you which side you are on.

---

## Networking

Port moves compose with the WSL modes; nothing here is WSL-specific. If Fusion
and OpenCode are not on the same loopback, the bind and route problems are
separate from the port choice, and the deep dive on both is in
[WSL-NETWORKING.md](WSL-NETWORKING.md) — including the security note on
non-loopback binding.

## The skill

Driving *this* add-in works better when the LLM has the operating manual:
[`skill/ai-drawer/SKILL.md`](../skill/ai-drawer/SKILL.md) documents our surface
specifically — the canonical loop, selection-handle addressing, units, and the
no-retry contract on mutations. Enabling it in OpenCode is described in
[INSTALL.md §4](INSTALL.md#4-enable-the-ai-drawer-skill-recommended). It is
advisory and changes no tool behaviour.
