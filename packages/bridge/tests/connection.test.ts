import type { AddressInfo } from "node:net";
import net from "node:net";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ResolvedHost } from "../src/config.js";
import { ConnectionMonitor } from "../src/connection.js";
import { FakeAddin } from "./fake-addin.js";

const IDLE_WINDOW_MS = 250;

function endpoint(port: number): ResolvedHost {
  return { host: "127.0.0.1", port, source: "default" };
}

/** Binds and immediately closes a socket, yielding a port that is definitely dead. */
async function deadPort(): Promise<number> {
  const server = net.createServer();
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  await new Promise<void>((resolve) => server.close(() => resolve()));
  return port;
}

describe("connection state machine", () => {
  let addin: FakeAddin;

  beforeEach(async () => {
    addin = new FakeAddin({ mode: "json" });
    await addin.start();
  });

  afterEach(async () => {
    await addin.close();
  });

  it("starts DISCONNECTED and promotes to CONNECTED on the first call", async () => {
    const monitor = new ConnectionMonitor(endpoint(addin.port));
    expect(monitor.currentState).toBe("DISCONNECTED");

    const outcome = await monitor.send({ method: "tools/call", params: { name: "get_viewport" } });
    expect(outcome.ok).toBe(true);
    expect(monitor.currentState).toBe("CONNECTED");
  });

  it("forwards a call and decodes the tool result", async () => {
    const monitor = new ConnectionMonitor(endpoint(addin.port));
    const outcome = await monitor.send({ method: "tools/call", params: { name: "get_viewport" } });
    expect(outcome.ok).toBe(true);
    if (!outcome.ok) return;
    const message = outcome.message as {
      result: { content: { text: string }[] };
    };
    expect(message.result.content[0]?.text).toBe("called get_viewport");
  });

  it("returns unreachable when the add-in is down", async () => {
    const port = await deadPort();
    const monitor = new ConnectionMonitor(endpoint(port));
    const outcome = await monitor.send({ method: "tools/call", params: { name: "get_viewport" } });

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.kind).toBe("unreachable");
    expect(monitor.currentState).toBe("DISCONNECTED");
    expect(monitor.lastErrorText).toContain("unreachable");
  });

  it("demotes and retries once when a connected socket dies", async () => {
    const monitor = new ConnectionMonitor(endpoint(addin.port));
    await monitor.send({ method: "ping" });
    expect(monitor.currentState).toBe("CONNECTED");

    await addin.close();
    const probesBefore = monitor.probeCount;
    const outcome = await monitor.send({ method: "tools/call", params: { name: "get_viewport" } });

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.kind).toBe("unreachable");
    expect(monitor.currentState).toBe("DISCONNECTED");
    // The failed forward plus exactly one inline probe — not a retry storm.
    expect(monitor.probeCount - probesBefore).toBe(1);
  });

  it("does NOT probe in the background while idle", async () => {
    const port = await deadPort();
    const monitor = new ConnectionMonitor(endpoint(port));
    expect(monitor.probeCount).toBe(0);

    await monitor.send({ method: "ping" });
    const probesAfterFailure = monitor.probeCount;
    expect(probesAfterFailure).toBe(1);

    // An idle window must not trigger any further probing: no busy-wait,
    // no timer, no CPU spin while OpenCode is not making requests.
    await delay(IDLE_WINDOW_MS);
    expect(monitor.probeCount).toBe(probesAfterFailure);
    await delay(IDLE_WINDOW_MS);
    expect(monitor.probeCount).toBe(probesAfterFailure);
    await delay(IDLE_WINDOW_MS);
    expect(monitor.probeCount).toBe(probesAfterFailure);
  });

  it("probes at most once per call", async () => {
    const port = await deadPort();
    const monitor = new ConnectionMonitor(endpoint(port));
    const before = monitor.probeCount;
    await monitor.send({ method: "ping" });
    expect(monitor.probeCount - before).toBe(1);
  });

  it("reconnects lazily when the add-in returns on the same port", async () => {
    const port = addin.port;
    const monitor = new ConnectionMonitor(endpoint(port));
    await monitor.send({ method: "ping" });
    expect(monitor.currentState).toBe("CONNECTED");

    // Kill the add-in mid-session.
    await addin.close();
    const down = await monitor.send({ method: "ping" });
    expect(down.ok).toBe(false);
    expect(monitor.currentState).toBe("DISCONNECTED");

    // No probing while nothing asks for the add-in.
    const idleProbes = monitor.probeCount;
    await delay(IDLE_WINDOW_MS);
    expect(monitor.probeCount).toBe(idleProbes);

    // Bring it back on the same port; the next call must lazily reconnect.
    addin = new FakeAddin({ mode: "json", port });
    await addin.start();
    const up = await monitor.send({ method: "tools/call", params: { name: "get_viewport" } });
    expect(up.ok).toBe(true);
    expect(monitor.currentState).toBe("CONNECTED");
  });

  it("always probes on demand for fusion_health, even when connected", async () => {
    const monitor = new ConnectionMonitor(endpoint(addin.port));
    await monitor.send({ method: "ping" });
    const probesBefore = monitor.probeCount;

    const report = await monitor.health();
    expect(report.connected).toBe(true);
    expect(monitor.probeCount).toBeGreaterThan(probesBefore);
    expect(report.host).toBe("127.0.0.1");
    expect(report.port).toBe(addin.port);
    expect(report.latency_ms).toBeGreaterThanOrEqual(0);
    expect(report.last_error).toBe(null);
  });

  it("reports disconnected health when the add-in is down", async () => {
    const port = await deadPort();
    const monitor = new ConnectionMonitor(endpoint(port));
    const report = await monitor.health();
    expect(report.connected).toBe(false);
    expect(report.latency_ms).toBe(null);
    expect(report.last_error).toContain("unreachable");
    expect(report.state).toBe("DISCONNECTED");
  });

  it("health probes never forward tool calls to the add-in", async () => {
    const monitor = new ConnectionMonitor(endpoint(addin.port));
    const before = addin.requests.filter((request) => request.body.includes("fusion_health")).length;
    await monitor.health();
    const after = addin.requests.filter((request) => request.body.includes("fusion_health")).length;
    expect(after).toBe(before);
  });

  it("uses monotonic request ids", async () => {
    const monitor = new ConnectionMonitor(endpoint(addin.port));
    await monitor.send({ method: "ping" });
    await monitor.send({ method: "ping" });
    const pings = addin.requests.filter((request) => request.body.includes('"ping"'));
    const ids = pings.map((request) => (JSON.parse(request.body) as { id: number }).id);
    expect(ids.length).toBeGreaterThanOrEqual(2);
    for (let index = 1; index < ids.length; index += 1) {
      expect(ids[index]).toBeGreaterThan(ids[index - 1] as number);
    }
  });
});

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
