# WSL networking — how OpenCode (WSL) reaches Fusion (Windows host)

This is the deep dive on the one genuinely hard part of the install: why a Windows
loopback address sometimes is, and sometimes is not, reachable from WSL. For the
install steps themselves see [INSTALL.md](INSTALL.md).

Everything below is verified against three source files:

- [`packages/addin/settings.py`](../packages/addin/settings.py) — the bind side
- [`packages/bridge/src/config.ts`](../packages/bridge/src/config.ts) — the
  resolution order on the client side
- [`packages/bridge/src/errors.ts`](../packages/bridge/src/errors.ts) — what the
  failure actually looks like

---

## The two separate problems

"WSL cannot reach Fusion" is really two independent questions, and conflating
them is the usual cause of confusion:

1. **Bind** — does the add-in's HTTP server accept connections on an address WSL
   can dial? Controlled by `MCP_SERVER_HOST` in `settings.py`.
2. **Route** — does WSL know an address that resolves to the Windows host?
   Controlled by the WSL networking mode, plus `FUSION_MCP_HOST` on the client.

The default `MCP_SERVER_HOST = "127.0.0.1"` is deliberately conservative. The
comment in `settings.py` says why:

> Loopback is the only safe default: the add-in serves a tool surface that can
> drive the whole Fusion process, so it must never be reachable from the network.

So the default is correct for native Windows and for mirrored WSL, and it is
exactly the thing that has to change for NAT-mode WSL.

---

## Client-side resolution order

The bridge resolves the endpoint in a fixed order, then caches the result. This
is the contract from `config.ts`, reproduced faithfully:

1. **`FUSION_MCP_HOST` / `FUSION_MCP_PORT` environment variables — explicit
   wins.** If `FUSION_MCP_HOST` is set and non-empty, it is used as-is, port
   defaulting to `8765` when unset or invalid. The bridge probes it, and —
   importantly — **never second-guesses it**: whether or not the probe succeeds,
   that address is what gets reported in every error message, so the text always
   names exactly what you configured.
2. **Default `127.0.0.1:8765`.** Probed first when no env var is set. This is the
   value that works for native Windows, and for mirrored-mode WSL.
3. **WSL gateway fallback.** Only if (1) is unset, (2) refuses the TCP connection,
   **and** the bridge is running under WSL. Detection is
   `isWsl()`: read `/proc/sys/kernel/osrelease` and lowercase-match `"microsoft"`.
   Candidates are collected in this order:
   - the gateway from `ip route show default`, parsed as `default via <ip>`
     (`defaultRouteGateway()`); this one is tried first because it is the address
     the vEthernet adapter actually routes through;
   - the first non-comment `nameserver` line in `/etc/resolv.conf`
     (`resolvNameserver()`), added only if it differs from the gateway.

   Each candidate is probed with an 800 ms connect timeout; the first that
   accepts is used with `source: "wsl-gateway"`.

**Caching.** Whichever endpoint succeeds is held in memory for the lifetime of
the bridge process. OpenCode spawns the bridge once per session, so a single
successful probe is authoritative until the process exits. Re-resolution is
deliberately **not** retried in the background: an endpoint that goes stale
mid-session stays stale until you restart the session. `getCachedHost()` exposes
the current value without probing, and `resetResolvedHost()` clears it (exported
for the test suite).

---

## Why NAT mode breaks, concretely

In **NAT** mode (the WSL default, and every older setup), WSL gets its own virtual
network with its own loopback. The Windows host appears to WSL as a gateway on a
`172.x` subnet (the exact range varies).

Two distinct `127.0.0.1` addresses now exist:

```
Windows:  127.0.0.1  →  Windows' own loopback (Fusion is listening here)
WSL:      127.0.0.1  →  WSL's own loopback     (nothing is listening here)
```

When the bridge inside WSL dials `127.0.0.1:8765`, that is the **WSL** loopback,
which has no server on it. The connection is refused, exactly as if Fusion were
not running — because from WSL's point of view, it isn't. This is why the failure
is a plain "connection refused" rather than a routing error: the address is
*valid*, it just points at the wrong machine's loopback.

In **mirrored** mode (Windows 11, WSL 2.0+, `.wslconfig` with
`networkingMode=mirrored`), WSL and Windows share the loopback interface, so
Windows' `127.0.0.1:8765` is directly dialable from WSL and no re-binding is
needed. `settings.py` calls this out explicitly:

> The WSL -> Windows host path can still reach it, because WSL can address the
> host's loopback directly (non-mirrored networking mode needs the host's
> vEthernet adapter IP instead…)

### The consequence for defaults

| Mode | `MCP_SERVER_HOST=127.0.0.1` reachable from WSL? | Action |
| --- | --- | --- |
| Mirrored | **Yes** — shared loopback | None. Defaults work. |
| NAT | **No** — WSL has its own loopback | Re-bind the add-in; client side auto-detects. |

---

## Finding the gateway IP

Inside WSL:

```bash
ip route show default
# default via 172.22.160.1 dev eth0
```

The address after `via` is the Windows host as seen from WSL. That is the value
to use for `MCP_SERVER_HOST` when you want the minimal-exposure bind, or for
`FUSION_MCP_HOST` when you are pinning the client side.

If `ip route` prints nothing, you are not in NAT mode — re-check
[INSTALL.md §Step 0](INSTALL.md#step-0-find-out-which-mode-you-are-in).

The bridge also consults `/etc/resolv.conf` as a secondary candidate, because on
some WSL builds the nameserver is the host's resolver and is reachable when the
default route is not. You normally do not need to care; the resolution order
handles it.

---

## Firewall: restricting the exposure

Binding `MCP_SERVER_HOST = "0.0.0.0"` opens TCP 8765 on **every** interface of the
Windows host — including your LAN and Wi-Fi. The server is unauthenticated and
its tool surface can drive the whole Fusion process, so this should not be left
wide open. Two mitigations, strongest first:

1. **Prefer the gateway IP over `0.0.0.0`.** Setting `MCP_SERVER_HOST` to the
   `default via` address binds only the WSL-facing virtual adapter. This is the
   option `settings.py` recommends, and it needs no firewall rule at all.
2. **If you must use `0.0.0.0`, scope it with a firewall rule.** Allow inbound
   TCP 8765 only from the WSL subnet (e.g. `172.22.160.0/20` — use the subnet
   your `ip route` / `ip addr` reports; it is not fixed). In PowerShell as
   administrator:

   ```powershell
   New-NetFirewallRule -DisplayName "Fusion MCP (WSL only)" `
     -Direction Inbound -Protocol TCP -LocalPort 8765 `
     -RemoteAddress 172.22.160.0/20 -Action Allow
   ```

   Then confirm nothing else can reach it from another device on the network.

---

## Security note

The add-in exposes an unauthenticated Streamable HTTP endpoint whose tools can
drive the entire Fusion process. Loopback is the only safe default and that is
why it is the default.

Choosing `0.0.0.0` is a real exposure: anything that can route to the host can
connect and invoke the tool surface. There is no authentication layer to fall
back on. Scope it to the WSL subnet with a firewall rule, and undo the change as
soon as you no longer need it. If a broader deployment is ever required, put a
real authenticating proxy in front rather than opening the port.

As a separate, unrelated matter: this project deliberately removed the upstream
tools that would have allowed arbitrary code execution. See the
[README](../README.md#security) — there is no `execute_python` and no generic
`call_autodesk_api` in this build.

---

## Debugging the resolution itself

- Call the bridge-owned `fusion_health` tool. It reports `host`, `port`,
  `connected`, `state` (`DISCONNECTED` / `PROBING` / `CONNECTED`), `latency_ms`,
  `protocol_version` and `last_error`. It probes on demand regardless of cached
  state, so it is the fastest way to see which endpoint you are actually talking
  to.
- Remember the cache: the bridge resolves **once per process**. If you change
  `settings.py` or your `.wslconfig` while a session is open, restart OpenCode
  (or at least the MCP server) — `resetResolvedHost()` is not wired to anything
  user-facing.
- Confirm the bind from the Windows side with
  `netstat -ano | findstr :8765` — the listening address shows whether your
  `settings.py` edit took effect.
- If you pinned `FUSION_MCP_HOST` and it is wrong, the bridge will **not** fall
  back to the gateway for you. Unset it and let the resolution order run.
