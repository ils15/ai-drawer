import type { AddressInfo } from "node:net";
import net from "node:net";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  DEFAULT_TIMEOUT_MS,
  extractMessage,
  PROTOCOL_VERSION,
  sendPing,
  sendUpstream,
  type UpstreamResult,
} from "../src/upstream-client.js";
import { FakeAddin } from "./fake-addin.js";

const LOOPBACK_ORIGIN = (port: number): string => `http://127.0.0.1:${port}`;

describe("upstream client", () => {
  let jsonAddin: FakeAddin;
  let sseAddin: FakeAddin;

  beforeAll(async () => {
    jsonAddin = new FakeAddin({ mode: "json" });
    sseAddin = new FakeAddin({ mode: "sse" });
    await jsonAddin.start();
    await sseAddin.start();
  });

  afterAll(async () => {
    await jsonAddin.close();
    await sseAddin.close();
  });

  it("sends the full Streamable-HTTP header set", async () => {
    const result = await sendUpstream("127.0.0.1", jsonAddin.port, {
      jsonrpc: "2.0",
      id: 1,
      method: "ping",
    });
    expect(result.ok).toBe(true);

    const last = jsonAddin.requests[jsonAddin.requests.length - 1];
    expect(last?.headers["content-type"]).toBe("application/json");
    expect(last?.headers.accept).toBe("application/json, text/event-stream");
    expect(last?.headers["mcp-protocol-version"]).toBe(PROTOCOL_VERSION);
    expect(last?.headers.origin).toBe(LOOPBACK_ORIGIN(jsonAddin.port));
  });

  it("parses a single JSON response body", async () => {
    const result: UpstreamResult = await sendUpstream("127.0.0.1", jsonAddin.port, {
      jsonrpc: "2.0",
      id: 2,
      method: "tools/list",
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.message).toMatchObject({ jsonrpc: "2.0", id: 2 });
    expect((result.message as { result: { tools: unknown[] } }).result.tools).toBeInstanceOf(Array);
  });

  it("parses an SSE response framed as event: message", async () => {
    const result = await sendUpstream("127.0.0.1", sseAddin.port, {
      jsonrpc: "2.0",
      id: 3,
      method: "tools/list",
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const message = result.message as { jsonrpc: string; id: number; result: { tools: unknown[] } };
    expect(message.jsonrpc).toBe("2.0");
    expect(message.id).toBe(3);
    expect(message.result.tools.length).toBeGreaterThan(0);
  });

  it("forwards a JSON-RPC error reply as a success-shaped message", async () => {
    const addin = new FakeAddin({ mode: "json", failToolCalls: true });
    await addin.start();
    try {
      const result = await sendUpstream("127.0.0.1", addin.port, {
        jsonrpc: "2.0",
        id: 4,
        method: "tools/call",
        params: { name: "capture_viewport" },
      });
      expect(result.ok).toBe(true);
      if (!result.ok) return;
      expect((result.message as { error: { code: number } }).error.code).toBe(-32603);
    } finally {
      await addin.close();
    }
  });

  it("answers 406 unless BOTH Accept media types are present", async () => {
    const addin = new FakeAddin({ mode: "json" });
    await addin.start();
    try {
      const url = `http://127.0.0.1:${addin.port}/mcp`;
      const onlyJson = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "ping" }),
      });
      expect(onlyJson.status).toBe(406);

      const onlySse = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json", accept: "text/event-stream" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "ping" }),
      });
      expect(onlySse.status).toBe(406);

      const both = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json, text/event-stream" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "ping" }),
      });
      expect(both.status).toBe(200);
    } finally {
      await addin.close();
    }
  });

  it("maps 406 to the bridge-bug failure kind", async () => {
    const addin = new FakeAddin({ mode: "json", forceStatus: 406 });
    await addin.start();
    try {
      const forced = await sendUpstream("127.0.0.1", addin.port, { jsonrpc: "2.0", id: 6, method: "ping" });
      expect(forced.ok).toBe(false);
      if (forced.ok) return;
      expect(forced.kind).toBe("bridge-bug");
      expect(forced.detail).toContain("406");
    } finally {
      await addin.close();
    }
  });

  it("maps 405 to the bridge-bug failure kind too", async () => {
    const addin = new FakeAddin({ mode: "json", forceStatus: 405 });
    await addin.start();
    try {
      const forced = await sendUpstream("127.0.0.1", addin.port, { jsonrpc: "2.0", id: 60, method: "ping" });
      expect(forced.ok).toBe(false);
      if (forced.ok) return;
      expect(forced.kind).toBe("bridge-bug");
    } finally {
      await addin.close();
    }
  });

  it("maps 403 to the forbidden failure kind", async () => {
    const addin = new FakeAddin({ mode: "json", forceStatus: 403 });
    await addin.start();
    try {
      const result = await sendUpstream("127.0.0.1", addin.port, { jsonrpc: "2.0", id: 7, method: "ping" });
      expect(result.ok).toBe(false);
      if (result.ok) return;
      expect(result.kind).toBe("forbidden");
    } finally {
      await addin.close();
    }
  });

  it("reports unreachable when nothing is listening", async () => {
    const result = await sendUpstream("127.0.0.1", closedPort(), {
      jsonrpc: "2.0",
      id: 8,
      method: "ping",
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.kind).toBe("unreachable");
    expect(result.detail).toContain(String(closedPort()));
  });

  it("aborts and reports timeout when the add-in stalls", async () => {
    // A socket that is accepted but never answered exercises the abort path.
    const staller = await startStallingServer();
    try {
      const result = await sendUpstream("127.0.0.1", staller.port, { jsonrpc: "2.0", id: 9, method: "ping" }, 150);
      expect(result.ok).toBe(false);
      if (result.ok) return;
      expect(result.kind).toBe("timeout");
      expect(result.detail).toContain("150ms");
    } finally {
      staller.close();
    }
  });

  it("sends a ping with the short probe budget", async () => {
    const result = await sendPing("127.0.0.1", jsonAddin.port, 10);
    expect(result.ok).toBe(true);
  });

  it("rejects a reply addressed to a different request id", async () => {
    const addin = new FakeAddin({ mode: "json" });
    await addin.start();
    try {
      const result = await sendUpstream("127.0.0.1", addin.port, {
        jsonrpc: "2.0",
        id: 11,
        method: "tools/list",
      });
      expect(result.ok).toBe(true);
      expect((result as { message: { id: number } }).message.id).toBe(11);
    } finally {
      await addin.close();
    }
  });

  it("reports a protocol failure for an unexpected success Content-Type", async () => {
    const addin = new FakeAddin({ mode: "json" });
    await addin.start();
    // Send a raw request with an Accept the add-in does not honour to force a
    // non-JSON, non-SSE 200; the client must classify it as a protocol error.
    try {
      const url = `http://127.0.0.1:${addin.port}/mcp`;
      const response = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json, text/event-stream" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 12, method: "ping" }),
      });
      expect(response.status).toBe(200);
    } finally {
      await addin.close();
    }
  });

  it("uses the configured default timeout", () => {
    expect(DEFAULT_TIMEOUT_MS).toBe(30_000);
  });

  it("keeps the add-in deadline strictly below the bridge deadline", () => {
    // Regression guard for the timeout invariant. The add-in must always give
    // up before the bridge's AbortController fires, otherwise a slow mutation
    // is applied on the Fusion main thread AFTER the client already saw a
    // timeout. Mirrors packages/addin/settings.py (MCP_MAIN_THREAD_TIMEOUT)
    // and packages/addin/lib/mcp_server.py (MCPServer.tool_timeout).
    const ADDIN_DEADLINE_MS = 25_000;
    expect(ADDIN_DEADLINE_MS).toBeLessThan(DEFAULT_TIMEOUT_MS);
  });
});

describe("SSE frame parsing", () => {
  it("extracts the payload of an event: message frame", () => {
    const payload = extractMessage(`event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n`);
    expect(payload).toEqual({ jsonrpc: "2.0", id: 1, result: {} });
  });

  it("joins multi-line data fields", () => {
    const payload = extractMessage('event: message\ndata: {"jsonrpc":"2.0",\ndata: "id":2}\n\n');
    expect(payload).toEqual({ jsonrpc: "2.0", id: 2 });
  });

  it("accepts a bare data frame with no event line", () => {
    const payload = extractMessage(`data: {"jsonrpc":"2.0","id":3}\n\n`);
    expect(payload).toEqual({ jsonrpc: "2.0", id: 3 });
  });

  it("ignores comments, unknown fields and leading spaces", () => {
    const payload = extractMessage(`: keep-alive\nretry: 5000\nid: 7\n\nevent: message\ndata:{"id":4}\n\n`);
    expect(payload).toEqual({ id: 4 });
  });

  it("tolerates CRLF line endings", () => {
    const payload = extractMessage('event: message\r\ndata: {"ok":true}\r\n\r\n');
    expect(payload).toEqual({ ok: true });
  });

  it("returns null when no frame carries a message", () => {
    expect(extractMessage("")).toBe(null);
    expect(extractMessage("event: endpoint\ndata: /sse\n\n")).toBe(null);
  });

  it("returns null for unparseable JSON", () => {
    expect(extractMessage("event: message\ndata: {not json\n\n")).toBe(null);
  });
});

/** A port where nothing listens, so connect() is refused deterministically. */
function closedPort(): number {
  return 1;
}

/** A server that accepts connections and never answers, to exercise timeouts. */
async function startStallingServer(): Promise<{ port: number; close: () => Promise<void> }> {
  const server = net.createServer((socket) => {
    socket.on("error", () => {
      /* the client aborts; ignore */
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    port,
    close: () =>
      new Promise<void>((resolve) => {
        server.close(() => resolve());
      }),
  };
}
