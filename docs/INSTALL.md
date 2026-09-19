# Installation — ai-drawer

**Status: alpha.** This connects OpenCode to Autodesk Fusion 360 over MCP. It can
inspect and drive an open Fusion document (viewport, selection, documentation
lookups). It **cannot create CAD geometry yet** — that lands in a later wave. See
[README](../README.md#status) and [docs/drawing-api-status.md](drawing-api-status.md)
(coming later).

The add-in folder is always named **`AutodeskFusionMCP`**. Do not rename it; the
upstream sync procedure and the error messages all assume that name.

---

## Which one am I?

| Your setup | Go to | Config needed |
| --- | --- | --- |
| OpenCode **and** Fusion on the **same Windows** machine | [Windows native](#1-windows-native) | None. Defaults work. |
| OpenCode inside **WSL**, Fusion on the **Windows host** | [WSL](#2-wsl-recommended-for-this-project) | Depends on networking mode — see below. |
| OpenCode and Fusion both on **macOS** | [macOS](#3-macos) | None for same-machine. |
| OpenCode on a **separate Linux box**, Fusion elsewhere | [WSL](#2-wsl-recommended-for-this-project) (the remote-host parts) | Bind `0.0.0.0` + point client at host IP. |

If you are not sure, you are almost certainly in the WSL row — that is the setup
this project targets.

---

## The two knobs

Everything network-related is two host/port pairs, one on each side:

| Setting | Lives in | Default | Meaning |
| --- | --- | --- | --- |
| `MCP_SERVER_HOST` / `MCP_SERVER_PORT` | add-in, [`packages/addin/settings.py`](../packages/addin/settings.py) | `127.0.0.1` / `8765` | What the server **binds** to, inside Fusion. |
| `FUSION_MCP_HOST` / `FUSION_MCP_PORT` | bridge, environment variables | unset → `127.0.0.1` / `8765` | What the client **connects** to. |

They only need to differ when Fusion and OpenCode are not on the same loopback.

---

## 1. Windows native

OpenCode and Fusion on the same Windows machine. **Zero network configuration** —
everything stays on loopback.

### Install the add-in

1. Copy the entire [`packages/addin`](../packages/addin) directory to
   `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\`.
2. Make sure the copied folder is named **`AutodeskFusionMCP`** (rename it if
   your copy landed as `addin`).
3. Open Fusion, press **Shift+S**, select the **Add-Ins** tab, select
   **AutodeskFusionMCP**, and click **Run**.
4. The server listens on `http://127.0.0.1:8765/mcp` (health check:
   `http://127.0.0.1:8765/health`).

### Install the bridge

```bash
cd packages/bridge
npm install
npm run build     # emits dist/bin.js
```

Requires Node 20 or newer.

### Point OpenCode at it

The bridge is a stdio MCP server (`ai-drawer-mcp`, entry point
`packages/bridge/dist/bin.js`). Register it in your OpenCode MCP config:

```json
{
  "mcpServers": {
    "ai-drawer": {
      "type": "local",
      "command": ["node", "/absolute/path/to/packages/bridge/dist/bin.js"],
      "enabled": true
    }
  }
}
```

**Environment variables (the exact two):**

- `FUSION_MCP_HOST` — connect to this host instead of `127.0.0.1`
- `FUSION_MCP_PORT` — connect to this port instead of `8765`

Both are optional on native Windows. Set them only if you changed
`MCP_SERVER_PORT` in `settings.py`.

Verify from PowerShell:

```powershell
curl http://127.0.0.1:8765/health
```

---

## 2. WSL (recommended for this project)

OpenCode runs inside WSL; Fusion runs on the Windows host. How this works depends
entirely on your WSL **networking mode**. This matters because the add-in binds
to `127.0.0.1` by default, and *which* `127.0.0.1` is reachable from WSL differs
by mode.

> The deep dive on every branch of this — including why the failure looks like
> "connection refused" — is in [WSL-NETWORKING.md](WSL-NETWORKING.md).

### Step 0: find out which mode you are in

Run **inside WSL**:

```bash
wsl.exe --version          # WSL version; <2.0 or "networkingMode not set" ⇒ NAT
ip route show default      # prints "default via <IP>" ⇒ you are in NAT mode
cat /etc/resolv.conf       # nameserver <IP> ⇒ also a NAT-mode hint
```

Rules of thumb:

- **Mirrored** — Windows 11, WSL 2.0+, and a `%UserProfile%\.wslconfig`
  containing `[wsl2]` `networkingMode=mirrored`. `ip route show default` prints
  *nothing* (no default route).
- **NAT** (the default, and everything on older setups) — `ip route show default`
  prints `default via <gateway-ip>`.

### Mirrored mode — zero config

When WSL networking is mirrored, WSL and Windows **share loopback**. The add-in's
default `MCP_SERVER_HOST=127.0.0.1` is directly reachable from inside WSL.

1. Install the add-in on Windows exactly as in [Windows native](#1-windows-native).
2. Build the bridge inside WSL (`npm install && npm run build` in
   `packages/bridge`).
3. Register the stdio server in your OpenCode config — same JSON as
   [above](#point-opencode-at-it). No env vars.

That is the whole setup. The bridge defaults to `127.0.0.1:8765` and it works.

### NAT mode — the add-in must be re-bound

In NAT mode, WSL has **its own** `127.0.0.1`, separate from Windows' loopback.
Windows' `127.0.0.1:8765` is *not* an address WSL can dial. You must change the
**bind** side; the client side is usually handled automatically.

**On the Windows host** — edit
[`packages/addin/settings.py`](../packages/addin/settings.py):

```python
MCP_SERVER_HOST = "0.0.0.0"
MCP_SERVER_PORT = 8765
```

Pick one of these two values:

| Value | Exposure | Use when |
| --- | --- | --- |
| the **WSL gateway IP** (e.g. `172.22.160.1`, from `ip route show default` in WSL) | Only the WSL virtual adapter. **Preferred.** | You want the smallest possible exposure. |
| `"0.0.0.0"` | Every interface on the Windows host — including your LAN/Wi-Fi. | The gateway IP does not work, or you run a remote-client setup. |

`0.0.0.0` exposes an unauthenticated tool surface that can drive your entire
Fusion process to anyone on the local network. If you use it, add a Windows
Firewall rule that allows inbound TCP 8765 **only from the WSL subnet**. See
[WSL-NETWORKING.md §Firewall](WSL-NETWORKING.md#firewall-restricting-the-exposure).

**In WSL** — usually nothing. If `FUSION_MCP_HOST` is unset, the bridge probes
`127.0.0.1` first, and when that refuses it detects WSL (`/proc/sys/kernel/osrelease`
contains `microsoft`) and falls back to the Windows host gateway IP from
`ip route show default`, then to the first nameserver in `/etc/resolv.conf`. The
first address that answers is cached for the life of the bridge process.

Set `FUSION_MCP_HOST` explicitly only if auto-detection picks the wrong address
(e.g. you have multiple host adapters), or to pin the endpoint so error messages
name exactly what you configured:

```bash
export FUSION_MCP_HOST=172.22.160.1   # the "default via" IP from ip route show default
export FUSION_MCP_PORT=8765
```

Note that an explicitly-set `FUSION_MCP_HOST` is **never** second-guessed: if it
cannot be reached, the bridge reports the error against that exact address rather
than falling back to the gateway.

Then register the stdio server in your OpenCode config exactly as in
[Windows native](#point-opencode-at-it).

### Verify

```bash
curl http://<host-ip>:8765/health     # from WSL, against the gateway IP
```

---

## 3. macOS

Short — this is not the primary path.

**Fusion and OpenCode on the same Mac** — identical to Windows native, only the
install path differs:

```
~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/
```

Copy `packages/addin` there as `AutodeskFusionMCP`, Shift+S → Add-Ins → Run, and
point OpenCode at the built bridge. Defaults (`127.0.0.1:8765`) work unchanged.

**OpenCode on a different machine** — the same rule as NAT-mode WSL: the host
running Fusion must bind something dialable, so set `MCP_SERVER_HOST="0.0.0.0"`
in `settings.py`, firewall TCP 8765 to the client's subnet, and set
`FUSION_MCP_HOST` (and, if needed, `FUSION_MCP_PORT`) in the client environment.
The WSL gateway auto-detection does **not** run on macOS or a plain Linux box —
`FUSION_MCP_HOST` is required there.

---

## Troubleshooting

The bridge's error text is written to be actionable. Match what you see to this
table.

| Symptom | Cause | Fix |
| --- | --- | --- |
| **`Fusion 360 is not reachable at <host>:<port>.`** (connection refused) | Fusion is not running, or the add-in is not started, or the address is wrong for your networking mode. | Open Fusion, **Shift+S → Add-Ins tab → AutodeskFusionMCP → Run**, then retry. If you are in NAT-mode WSL, confirm `MCP_SERVER_HOST` in `settings.py` is off loopback — see [WSL-NETWORKING.md](WSL-NETWORKING.md). |
| **`... Open Fusion and start the 'AutodeskFusionMCP' add-in (Shift+S → Add-Ins tab → Run), then retry.`** | Same as above — this is the second line of the same message, naming the exact add-in. | Same as above. |
| **`... If Fusion is on another machine set FUSION_MCP_HOST.`** | The bridge reached the end of its resolution order and nothing answered. | In WSL this usually means the add-in is still on `127.0.0.1` while you are in NAT mode. Re-bind it (above) or set `FUSION_MCP_HOST`. |
| **`The Fusion add-in at <host>:<port> rejected the request (HTTP 403).`** | The request **reached** Fusion but was refused on origin grounds. The add-in only accepts requests carrying no `Origin` header, or `Origin: http://localhost:<port>` / `http://127.0.0.1:<port>`. | The bridge always sends a synthetic loopback `Origin`, so with shipped defaults this should not occur. If you see it, you have either pointed a **browser**-style client at the add-in, or changed the add-in's `allowed_origins`. Connect through the bridge, not directly. |
| **`ai-drawer-mcp bridge bug: upstream answered HTTP 405/406. This should be impossible in a released build. Please report it.`** | A protocol contract violation **by the bridge itself**, not a config problem. It is surfaced loudly on purpose. | Do not try to configure around it. [Report it.](https://github.com/frankhommers/autodesk-fusion-mcp/issues) |
| **Timeout: request hangs, then fails** | The tool reached Fusion but the Fusion **main thread** never answered within `MCP_MAIN_THREAD_TIMEOUT` (120 s in `settings.py`). Usually Fusion is busy, frozen, or showing a modal dialog. | Dismiss any blocking dialog in Fusion. If it recurs, the add-in's log (Fusion's text commands palette / output) shows whether your handler threw. |
| **`fusion_health` says connected, but every tool fails** | Health only proves the HTTP endpoint is alive. Tool execution still needs the add-in's main-thread dispatch to work, and a tool can fail on its own merits (tier (b)). | Read the failure text the tool returns — it is meant to be reasoned about and retried. If *all* tools fail with the same unreachable-style message, the cached endpoint went stale; restart the OpenCode session (the bridge resolves once per process). |

### Checking which endpoint the bridge actually picked

`fusion_health` reports `host`, `port`, `state`, `latency_ms` and `last_error`,
so you can see whether it resolved from `env`, `default`, or `wsl-gateway`. Call
it first whenever anything connection-related looks wrong — it probes on demand
and does not depend on the cached state.
