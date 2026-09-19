/**
 * Host/port resolution for the Fusion add-in endpoint.
 *
 * Resolution order, per the bridge contract:
 *  1. FUSION_MCP_HOST / FUSION_MCP_PORT environment variables (explicit wins).
 *  2. Default 127.0.0.1:8765 (Fusion on the same host, or WSL mirrored mode).
 *  3. WSL fallback — if 127.0.0.1 refuses and we are running under WSL,
 *     resolve the Windows host gateway IP from `ip route show default` and/or
 *     the first nameserver in /etc/resolv.conf, try it, then cache whichever
 *     host actually answers for the lifetime of this process.
 *
 * A resolved endpoint is cached in memory: OpenCode spawns the bridge once
 * per session, so one successful probe is authoritative until the process
 * exits. Re-resolution is deliberately NOT retried in the background.
 */

import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import net from "node:net";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export const DEFAULT_HOST = "127.0.0.1";
export const DEFAULT_PORT = 8765;
const ENV_HOST = "FUSION_MCP_HOST";
const ENV_PORT = "FUSION_MCP_PORT";
const OSRELEASE_PATH = "/proc/sys/kernel/osrelease";
const RESOLV_PATH = "/etc/resolv.conf";
const WSL_MARKER = "microsoft";
const PROBE_TIMEOUT_MS = 800;

/** Where a resolved endpoint came from. */
export type HostSource = "env" | "default" | "wsl-gateway";

/** The endpoint the bridge will talk to. */
export interface ResolvedHost {
  readonly host: string;
  readonly port: number;
  readonly source: HostSource;
}

/** Cached working endpoint; null until a probe succeeds. */
let cachedHost: ResolvedHost | null = null;

/**
 * Resolves the add-in endpoint. Always returns a value, even when nothing is
 * reachable — callers need a concrete host to build actionable error text.
 * The first endpoint that accepts a TCP connection is cached for the process.
 */
export async function resolveHost(): Promise<ResolvedHost> {
  if (cachedHost !== null) return cachedHost;

  const envHost = process.env[ENV_HOST];
  const envPort = parsePort(process.env[ENV_PORT]);

  if (envHost !== undefined && envHost.length > 0) {
    const explicit: ResolvedHost = { host: envHost, port: envPort ?? DEFAULT_PORT, source: "env" };
    if (await probeHost(explicit.host, explicit.port)) cachedHost = explicit;
    // Never second-guess an explicitly configured host. Report it as-is so the
    // error text names exactly what the user configured.
    return explicit;
  }

  const local: ResolvedHost = { host: DEFAULT_HOST, port: envPort ?? DEFAULT_PORT, source: "default" };
  if (await probeHost(local.host, local.port)) {
    cachedHost = local;
    return local;
  }

  const wsl = await tryWslGateway(envPort ?? DEFAULT_PORT);
  if (wsl !== null) {
    cachedHost = wsl;
    return wsl;
  }

  return local;
}

/** Clears the cached endpoint. Exported for tests. */
export function resetResolvedHost(): void {
  cachedHost = null;
}

/** The currently resolved endpoint without re-probing; null before first resolve. */
export function getCachedHost(): ResolvedHost | null {
  return cachedHost;
}

/**
 * TCP liveness probe. True when a connection to host:port is accepted.
 * Never throws: a refused or timing-out port is a normal outcome here.
 */
export async function probeHost(host: string, port: number, timeoutMs: number = PROBE_TIMEOUT_MS): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    let settled = false;
    const socket = net.createConnection({ host, port });
    const timer = setTimeout(() => finish(false), timeoutMs);

    const finish = (value: boolean): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      resolve(value);
    };

    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
  });
}

/** True when running under WSL (osrelease contains "microsoft"). */
export async function isWsl(): Promise<boolean> {
  try {
    const osrelease = await readFile(OSRELEASE_PATH, "utf8");
    return osrelease.toLowerCase().includes(WSL_MARKER);
  } catch {
    // Not Linux, or unreadable — definitely not WSL.
    return false;
  }
}

/** Resolves the WSL gateway candidates, preferring the default route. */
async function tryWslGateway(port: number): Promise<ResolvedHost | null> {
  if (!(await isWsl())) return null;

  const candidates: string[] = [];
  const gateway = await defaultRouteGateway();
  if (gateway !== null) candidates.push(gateway);
  const nameserver = await resolvNameserver();
  if (nameserver !== null && !candidates.includes(nameserver)) candidates.push(nameserver);

  for (const host of candidates) {
    if (await probeHost(host, port)) return { host, port, source: "wsl-gateway" };
  }
  return null;
}

/** Parses the `default via <ip>` entry from `ip route show default`. */
export async function defaultRouteGateway(): Promise<string | null> {
  try {
    const { stdout } = await execFileAsync("ip", ["route", "show", "default"]);
    const match = /default\s+via\s+(\d{1,3}(?:\.\d{1,3}){3})/.exec(stdout);
    return match?.[1] ?? null;
  } catch {
    return null;
  }
}

/** Reads the first nameserver from /etc/resolv.conf. */
export async function resolvNameserver(): Promise<string | null> {
  try {
    const contents = await readFile(RESOLV_PATH, "utf8");
    for (const line of contents.split("\n")) {
      const trimmed = line.trim();
      if (trimmed.startsWith("#") || trimmed.startsWith(";")) continue;
      const match = /^nameserver\s+(\d{1,3}(?:\.\d{1,3}){3})/.exec(trimmed);
      if (match?.[1] !== undefined) return match[1];
    }
    return null;
  } catch {
    return null;
  }
}

/** Parses a valid TCP port, or null when absent or out of range. */
function parsePort(raw: string | undefined): number | null {
  if (raw === undefined) return null;
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) return null;
  return parsed;
}
