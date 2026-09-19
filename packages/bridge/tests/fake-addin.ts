/**
 * A fake AutodeskFusionMCP add-in, for tests that must not depend on Fusion.
 *
 * Implements the same Streamable-HTTP contract the real add-in serves:
 *  - answers POST /mcp only
 *  - answers 406 unless BOTH Accept media types are present
 *  - can reply with a single JSON document or an SSE stream
 *  - records every request so tests can assert on headers and forwarding
 */

import http from "node:http";
import type { AddressInfo } from "node:net";
import type { Tool } from "@modelcontextprotocol/sdk/types.js";
import { PROTOCOL_VERSION } from "../src/upstream-client.js";

export type ReplyMode = "json" | "sse";

export interface FakeAddinOptions {
  /** Reply framing: a single JSON document, or an SSE stream. */
  mode?: ReplyMode;
  /** Tools advertised by tools/list. Defaults to the Wave-1 surface. */
  tools?: Tool[];
  /** Enforce the Accept contract (406 unless both types are present). */
  requireBothAccepts?: boolean;
  /** Reject every request with this HTTP status instead of answering. */
  forceStatus?: number;
  /** Fail tool calls with a JSON-RPC error object (tier b path). */
  failToolCalls?: boolean;
  /** Bind this port instead of an ephemeral one; needed for restart tests. */
  port?: number;
}

export interface RecordedRequest {
  method: string;
  url: string;
  headers: http.IncomingHttpHeaders;
  body: string;
}

/** The Wave-1 surface plus one deliberately-dangerous advertisement. */
export const ADVERTISED_TOOLS: Tool[] = [
  { name: "capture_viewport", description: "Capture the viewport.", inputSchema: { type: "object", properties: {} } },
  { name: "get_viewport", description: "Get viewport size.", inputSchema: { type: "object", properties: {} } },
  { name: "set_viewport", description: "Set viewport size.", inputSchema: { type: "object", properties: {} } },
  {
    name: "get_active_selection",
    description: "Get the active selection.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "fetch_api_documentation",
    description: "Fetch API documentation.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "fetch_online_documentation",
    description: "Fetch online documentation.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "fetch_design_guide",
    description: "Fetch the design guide.",
    inputSchema: { type: "object", properties: {} },
  },
  // Advertised by a hostile or stale add-in; must never reach the LLM.
  {
    name: "execute_python",
    description: "Run arbitrary Python inside Fusion.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "create_sketch",
    description: "Wave-3 tool, not yet enabled.",
    inputSchema: { type: "object", properties: {} },
  },
];

export class FakeAddin {
  private server: http.Server;
  private socket?: http.Server;
  public readonly requests: RecordedRequest[] = [];
  public readonly forwardedCalls: string[] = [];

  constructor(private readonly options: FakeAddinOptions = {}) {}

  get port(): number {
    const address = this.server.address() as AddressInfo | null;
    if (address === null) throw new Error("fake add-in is not listening");
    return address.port;
  }

  get url(): string {
    return `http://127.0.0.1:${this.port}/mcp`;
  }

  get mode(): ReplyMode {
    return this.options.mode ?? "json";
  }

  async start(): Promise<void> {
    this.server = http.createServer((req, res) => this.handle(req, res));
    const port = this.options.port ?? 0;
    await new Promise<void>((resolve) => this.server.listen(port, "127.0.0.1", resolve));
  }

  async close(): Promise<void> {
    await new Promise<void>((resolve) => this.server.close(() => resolve()));
    this.socket?.close();
  }

  private async handle(request: http.IncomingMessage, response: http.ServerResponse): Promise<void> {
    const body = await readBody(request);
    this.requests.push({
      method: request.method ?? "GET",
      url: request.url ?? "/",
      headers: request.headers,
      body,
    });

    if (request.url !== "/mcp" || request.method !== "POST") {
      response.writeHead(404, { "content-type": "application/json" });
      response.end(JSON.stringify({ jsonrpc: "2.0", error: { code: -32601, message: "not found" } }));
      return;
    }

    if (this.options.forceStatus !== undefined) {
      response.writeHead(this.options.forceStatus, { "content-type": "application/json" });
      response.end(JSON.stringify({ jsonrpc: "2.0", error: { code: -32000, message: "forced" } }));
      return;
    }

    if (this.options.requireBothAccepts !== false) {
      const accept = request.headers.accept ?? "";
      if (!accept.includes("application/json") || !accept.includes("text/event-stream")) {
        response.writeHead(406, { "content-type": "application/json" });
        response.end(JSON.stringify({ jsonrpc: "2.0", error: { code: -32000, message: "not acceptable" } }));
        return;
      }
    }

    const payload = JSON.parse(body) as { id: number; method: string; params?: unknown };
    const reply = this.answer(payload);
    this.writeReply(response, reply);
  }

  /** Builds the JSON-RPC reply for one request. */
  private answer(payload: { id: number; method: string; params?: unknown }): unknown {
    switch (payload.method) {
      case "ping":
        return { jsonrpc: "2.0", id: payload.id, result: {} };
      case "initialize":
        return {
          jsonrpc: "2.0",
          id: payload.id,
          result: {
            protocolVersion: PROTOCOL_VERSION,
            capabilities: { tools: {} },
            serverInfo: { name: "AutodeskFusionMCP", version: "1.4.1" },
          },
        };
      case "tools/list":
        return { jsonrpc: "2.0", id: payload.id, result: { tools: this.options.tools ?? ADVERTISED_TOOLS } };
      case "tools/call": {
        const params = (payload.params ?? {}) as { name?: string };
        const name = params.name ?? "<unknown>";
        this.forwardedCalls.push(name);
        if (this.options.failToolCalls === true) {
          return {
            jsonrpc: "2.0",
            id: payload.id,
            error: { code: -32603, message: `tool '${name}' exploded` },
          };
        }
        return {
          jsonrpc: "2.0",
          id: payload.id,
          result: { content: [{ type: "text", text: `called ${name}` }] },
        };
      }
      default:
        return {
          jsonrpc: "2.0",
          id: payload.id,
          error: { code: -32601, message: `method not found: ${payload.method}` },
        };
    }
  }

  /** Frames the reply as JSON or as an SSE stream, per the configured mode. */
  private writeReply(response: http.ServerResponse, reply: unknown): void {
    const json = JSON.stringify(reply);
    if (this.options.mode === "sse") {
      response.writeHead(200, { "content-type": "text/event-stream" });
      response.write(`event: message\ndata: ${json}\n\n`);
      response.end();
      return;
    }
    response.writeHead(200, { "content-type": "application/json" });
    response.end(json);
  }
}

function readBody(request: http.IncomingMessage): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    request.on("error", reject);
  });
}
