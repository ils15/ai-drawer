/**
 * Stateless Streamable-HTTP client for the Fusion add-in.
 *
 * Every call is one POST: no session id, no resumption token, no
 * reconnection, no client-side state. The add-in inside Fusion owns all
 * state, so a Fusion restart needs no bridge handshake to recover.
 *
 * Wire contract (enforced by the add-in):
 *   POST http://<host>:<port>/mcp
 *     Content-Type: application/json
 *     Accept: application/json, text/event-stream    (BOTH required)
 *     MCP-Protocol-Version: 2026-07-28
 *     Origin: http://127.0.0.1:<port>                (synthetic, see below)
 *
 * Both response shapes are handled:
 *   200 + application/json       → single JSON-RPC message in the body
 *   200 + text/event-stream      → SSE; the message arrives as an
 *                                  `event: message` / `data:` frame
 *
 * Status mapping:
 *   405 / 406  bridge bug   — the contract was violated; must never happen
 *   403       forbidden     — origin/config error
 *   refused   unreachable   — add-in down
 *
 * The synthetic Origin header is why this client is hand-rolled rather than
 * built on the SDK's StreamableHTTPClientTransport: that class is
 * session-oriented (session ids, resumption tokens, reconnection backoff),
 * offers no hook for a fixed Origin, and hides the SSE parsing that the
 * tier mapping below depends on.
 */

import type { JsonRpcMessage, JsonRpcRequest } from "./json-rpc.js";
import { asJsonRpcError, asJsonRpcSuccess } from "./json-rpc.js";

export const PROTOCOL_VERSION = "2026-07-28";
export const MCP_PATH = "/mcp";
export const DEFAULT_TIMEOUT_MS = 30_000;
export const PING_TIMEOUT_MS = 2_000;

/** Why an upstream exchange failed. Drives the error-tier mapping. */
export type UpstreamFailureKind =
  | "unreachable" // connection refused / host down  → tier (c)
  | "timeout" // request exceeded its budget         → tier (c)
  | "forbidden" // HTTP 403 from the add-in
  | "bridge-bug" // HTTP 405/406 — contract violation, must never happen
  | "protocol"; // anything else, including malformed bodies

/** Success carries the decoded JSON-RPC message; failure carries a reason. */
export type UpstreamResult =
  | { readonly ok: true; readonly message: JsonRpcMessage }
  | { readonly ok: false; readonly kind: UpstreamFailureKind; readonly detail: string };

/**
 * Sends one JSON-RPC request to the add-in and returns the decoded message.
 * Never throws: every failure is surfaced as a `kind` the caller maps onto an
 * error tier.
 */
export async function sendUpstream(
  host: string,
  port: number,
  request: JsonRpcRequest,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<UpstreamResult> {
  const url = `http://${host}:${port}${MCP_PATH}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        // BOTH media types must be present or the add-in answers 406.
        accept: "application/json, text/event-stream",
        "mcp-protocol-version": PROTOCOL_VERSION,
        // The add-in validates Origin. The bridge is a local proxy, so it
        // advertises the loopback origin it is acting on behalf of.
        origin: `http://127.0.0.1:${port}`,
      },
      body: JSON.stringify(request),
      signal: controller.signal,
    });

    switch (response.status) {
      case 200:
        return await decodeBody(request, response);
      case 403:
        return fail("forbidden", `upstream rejected the request at ${url}`);
      case 405:
      case 406:
        return fail(
          "bridge-bug",
          `upstream returned HTTP ${response.status} at ${url}; the bridge sent an incomplete Streamable-HTTP header set`,
        );
      default:
        return fail("protocol", `upstream returned HTTP ${response.status} at ${url}`);
    }
  } catch (error) {
    if (controller.signal.aborted) return fail("timeout", `request to ${url} exceeded ${timeoutMs}ms`);
    if (errorCode(error) === "ECONNREFUSED") return fail("unreachable", `connection refused at ${url}`);
    // Any other network failure is treated as unreachable so the tier-(c)
    // text tells the user how to recover. The endpoint is named here for the
    // same reason as the refused branch: a bare "fetch failed" is not
    // actionable and hides which host was attempted.
    return fail("unreachable", `${describe(error)} at ${url}`);
  } finally {
    clearTimeout(timer);
  }
}

/** Sends a JSON-RPC `ping`, the probe used by the connection state machine. */
export function sendPing(
  host: string,
  port: number,
  id: number,
  timeoutMs: number = PING_TIMEOUT_MS,
): Promise<UpstreamResult> {
  return sendUpstream(host, port, { jsonrpc: "2.0", id, method: "ping" }, timeoutMs);
}

/** Reads a 200 response, dispatching on its Content-Type. */
async function decodeBody(request: JsonRpcRequest, response: Response): Promise<UpstreamResult> {
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("text/event-stream")) {
    const payload = extractMessage(await response.text());
    if (payload === null) return fail("protocol", "SSE stream ended without a message frame");
    return decodeMessage(request, payload);
  }

  if (contentType.includes("application/json")) {
    const text = await response.text();
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      return fail("protocol", `upstream sent an unparseable JSON body: ${truncate(text)}`);
    }
    return decodeMessage(request, parsed);
  }

  return fail("protocol", `upstream answered 200 with unexpected Content-Type '${contentType}'`);
}

/** Validates a decoded payload as a JSON-RPC message for our request id. */
function decodeMessage(request: JsonRpcRequest, payload: unknown): UpstreamResult {
  const error = asJsonRpcError(payload);
  if (error !== null) {
    return error.id === request.id
      ? { ok: true, message: error }
      : fail("protocol", `upstream error response carried id ${error.id}, expected ${request.id}`);
  }

  const success = asJsonRpcSuccess(payload);
  if (success === null) return fail("protocol", "upstream body was not a JSON-RPC message");

  return success.id === request.id
    ? { ok: true, message: success }
    : fail("protocol", `upstream response carried id ${success.id}, expected ${request.id}`);
}

function fail(kind: UpstreamFailureKind, detail: string): UpstreamResult {
  return { ok: false, kind, detail };
}

/** One decoded SSE frame. */
interface SseFrame {
  event: string | null;
  data: string[];
}

/**
 * Pulls the JSON-RPC payload out of an SSE document.
 *
 * The add-in may frame the reply as an `event: message` block or, less
 * conventionally, as a bare `data:` block; both are accepted. Multi-line
 * `data:` fields are joined with "\n" per the SSE spec. Comment lines and
 * unknown fields are ignored.
 */
export function extractMessage(sseText: string): unknown {
  const frames: SseFrame[] = [];
  let current: SseFrame | null = null;

  const flush = (): void => {
    if (current !== null && current.data.length > 0) frames.push(current);
    current = null;
  };

  for (const rawLine of sseText.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (line === "") {
      flush();
      continue;
    }
    if (line.startsWith(":")) continue; // SSE comment

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const rawValue = colon === -1 ? "" : line.slice(colon + 1);
    const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue;

    if (field === "event" || field === "data") {
      if (current === null) current = { event: null, data: [] };
      if (field === "event") current.event = value;
      else current.data.push(value);
    }
  }
  flush();

  const explicit = frames.find((frame) => frame.event === "message");
  const chosen = explicit ?? frames[0];
  if (chosen === undefined) return null;

  try {
    return JSON.parse(chosen.data.join("\n"));
  } catch {
    return null;
  }
}

/** Walks a fetch error and its `cause` chain looking for a libuv errno code. */
function errorCode(error: unknown): string | null {
  let cursor: unknown = error;
  for (let depth = 0; depth < 4 && cursor !== null; depth += 1) {
    if (typeof cursor !== "object") return null;
    const candidate = (cursor as { code?: unknown }).code;
    if (typeof candidate === "string") return candidate;
    cursor = (cursor as { cause?: unknown }).cause;
  }
  return null;
}

function describe(error: unknown): string {
  if (error instanceof Error) return error.message.length > 0 ? error.message : "unknown network error";
  return "unknown network error";
}

function truncate(text: string): string {
  return text.length > 120 ? `${text.slice(0, 120)}…` : text;
}
