/**
 * Host resolution tests. `node:net`, `node:fs/promises` and `node:child_process`
 * are mocked so these run anywhere — including a container that is not WSL.
 */

import { EventEmitter } from "node:events";
import { promisify } from "node:util";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Hosts the mocked socket layer considers reachable.
const reachable = new Set<string>();

vi.mock("node:net", () => ({
  default: {
    createConnection: ({ host }: { host: string }) => {
      const socket: EventEmitter & { destroy: () => void } = Object.assign(new EventEmitter(), {
        destroy: () => undefined,
      });
      queueMicrotask(() => {
        if (reachable.has(host)) socket.emit("connect");
        else socket.emit("error", Object.assign(new Error("refused"), { code: "ECONNREFUSED" }));
      });
      return socket;
    },
  },
}));

let osrelease = "5.15.153.1-microsoft-standard-WSL2";
let resolv = "# generated\nnameserver 172.20.0.1\n";
let routeTable = "default via 172.20.0.1 dev eth0\n";

vi.mock("node:fs/promises", () => ({
  readFile: vi.fn(async (path: string) => {
    if (path === "/proc/sys/kernel/osrelease") return osrelease;
    if (path === "/etc/resolv.conf") return resolv;
    throw Object.assign(new Error("ENOENT"), { code: "ENOENT" });
  }),
}));

vi.mock("node:child_process", () => {
  // The real child_process.execFile carries a util.promisify.custom hook that
  // resolves { stdout, stderr }; a plain errback mock resolves only the first
  // callback value, which would silently starve the route table.
  const exec = (
    file: string,
    args: readonly string[],
    callback: (error: Error | null, stdout: string, stderr: string) => void,
  ): void => {
    if (file === "ip" && args.includes("default")) callback(null, routeTable, "");
    else callback(Object.assign(new Error("ENOENT"), { code: "ENOENT" }), "", "");
  };

  return {
    execFile: Object.assign(vi.fn(exec), {
      [promisify.custom]: (file: string, args: readonly string[]) =>
        new Promise<{ stdout: string; stderr: string }>((resolve, reject) => {
          exec(file, args, (error, stdout, stderr) => {
            if (error !== null) reject(error);
            else resolve({ stdout, stderr });
          });
        }),
    }),
  };
});

const { defaultRouteGateway, isWsl, probeHost, resetResolvedHost, resolvNameserver, resolveHost } = await import(
  "../src/config.js"
);

describe("host resolution", () => {
  beforeEach(() => {
    reachable.clear();
    reachable.add("127.0.0.1");
    osrelease = "5.15.153.1-microsoft-standard-WSL2";
    resolv = "# generated\nnameserver 172.20.0.1\n";
    routeTable = "default via 172.20.0.1 dev eth0\n";
    resetResolvedHost();
  });

  it("uses FUSION_MCP_HOST and FUSION_MCP_PORT when both are set", async () => {
    process.env.FUSION_MCP_HOST = "10.0.0.9";
    process.env.FUSION_MCP_PORT = "9999";
    try {
      const host = await resolveHost();
      expect(host).toEqual({ host: "10.0.0.9", port: 9999, source: "env" });
    } finally {
      delete process.env.FUSION_MCP_HOST;
      delete process.env.FUSION_MCP_PORT;
    }
  });

  it("falls back to the default port when the env port is invalid", async () => {
    process.env.FUSION_MCP_HOST = "10.0.0.9";
    process.env.FUSION_MCP_PORT = "not-a-port";
    try {
      const host = await resolveHost();
      expect(host).toEqual({ host: "10.0.0.9", port: 8765, source: "env" });
    } finally {
      delete process.env.FUSION_MCP_HOST;
      delete process.env.FUSION_MCP_PORT;
    }
  });

  it("defaults to 127.0.0.1:8765 when loopback answers", async () => {
    const host = await resolveHost();
    expect(host).toEqual({ host: "127.0.0.1", port: 8765, source: "default" });
  });

  it("resolves the WSL gateway when 127.0.0.1 refuses", async () => {
    reachable.delete("127.0.0.1");
    reachable.add("172.20.0.1");
    expect(await isWsl()).toBe(true);

    const host = await resolveHost();
    expect(host).toEqual({ host: "172.20.0.1", port: 8765, source: "wsl-gateway" });
  });

  it("prefers the default-route gateway over the resolv.conf nameserver", async () => {
    reachable.delete("127.0.0.1");
    reachable.add("172.20.0.1");
    routeTable = "default via 192.168.42.1 dev eth1\n";
    resolv = "nameserver 172.20.0.1\n";
    reachable.add("172.20.0.1");
    // 192.168.42.1 is NOT reachable, so the nameserver must win.
    const host = await resolveHost();
    expect(host.host).toBe("172.20.0.1");
    expect(host.source).toBe("wsl-gateway");
  });

  it("falls back to the nameserver when ip route yields nothing", async () => {
    reachable.delete("127.0.0.1");
    routeTable = "";
    reachable.add("10.1.2.3");
    resolv = "nameserver 10.1.2.3\n";

    const host = await resolveHost();
    expect(host.host).toBe("10.1.2.3");
  });

  it("caches the first working endpoint for the process", async () => {
    reachable.delete("127.0.0.1");
    reachable.add("172.20.0.1");
    const first = await resolveHost();
    reachable.add("127.0.0.1");
    const second = await resolveHost();
    expect(second).toBe(first);
  });

  it("returns the default endpoint when nothing is reachable", async () => {
    reachable.delete("127.0.0.1");
    routeTable = "";
    resolv = "";
    const host = await resolveHost();
    expect(host).toEqual({ host: "127.0.0.1", port: 8765, source: "default" });
  });

  it("does not attempt WSL resolution outside WSL", async () => {
    osrelease = "6.8.0-45-generic";
    reachable.delete("127.0.0.1");
    const host = await resolveHost();
    expect(host.source).toBe("default");
  });

  it("parses the default route gateway", async () => {
    routeTable = "default via 172.31.32.1 dev eth0 proto kernel\n172.31.32.0/20 dev eth0\n";
    expect(await defaultRouteGateway()).toBe("172.31.32.1");
  });

  it("parses the first resolv.conf nameserver", async () => {
    resolv = "# comment\nnameserver 8.8.8.8\nnameserver 8.8.4.4\n";
    expect(await resolvNameserver()).toBe("8.8.8.8");
  });

  it("probes a reachable and an unreachable host", async () => {
    expect(await probeHost("127.0.0.1", 8765)).toBe(true);
    expect(await probeHost("203.0.113.1", 8765)).toBe(false);
  });
});
