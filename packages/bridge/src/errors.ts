/**
 * Three-tier error model for the bridge.
 *
 * The tiers are deliberately DISTINCT. Never collapse them: each one means a
 * different thing to the LLM client and to the user.
 *
 *  (a) JSON-RPC protocol error  — the request itself was malformed or
 *      unsupported. Returned as a real JSON-RPC error object so the client
 *      knows the server (not the tool) rejected it.
 *
 *  (b) Tool execution failure   — the add-in answered, but the tool failed.
 *      Returned as `result.isError = true` with text content, so the LLM can
 *      reason about the failure and retry differently.
 *
 *  (c) Add-in unreachable      — Fusion or the add-in is not running.
 *      Synthesized `isError = true` result carrying ACTIONABLE user-facing
 *      text naming the exact endpoint that was tried.
 */

import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import type { JsonRpcErrorBody } from "./json-rpc.js";

/** Standard JSON-RPC error codes emitted for tier (a). */
export const RpcCode = {
  PARSE_ERROR: -32700,
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INVALID_PARAMS: -32602,
  INTERNAL_ERROR: -32603,
} as const;

/** MCP text content block — the only content shape the bridge synthesizes. */
export interface TextContent {
  readonly type: "text";
  readonly text: string;
}

/**
 * Shape returned by tools/call.
 *
 * This IS the SDK's CallToolResult: a bridge tool result is an MCP tool
 * result, so handlers return them with no cast. `isError` distinguishes
 * tiers (b) and (c) from a genuine success.
 */
export type ToolResult = CallToolResult;

/** Tier (a) — builds a JSON-RPC protocol error object. */
export function protocolError(code: number, message: string, data?: unknown): JsonRpcErrorBody {
  return data === undefined ? { code, message } : { code, message, data };
}

/** The single constructor every text result shares, so tiers never drift in shape. */
function textResult(text: string, isError: boolean): ToolResult {
  return { content: [{ type: "text", text }], isError };
}

/** Tier (b) — the tool ran but failed. Message should describe WHAT failed. */
export function toolFailure(message: string, detail?: string): ToolResult {
  const text = detail === undefined || detail === "" ? message : `${message}\n\n${detail}`;
  return textResult(text, true);
}

/**
 * Tier (c) — Fusion is unreachable. The message must be actionable and must
 * name the endpoint actually attempted, per the bridge contract.
 */
export function unreachableFailure(host: string, port: number, detail?: string): ToolResult {
  const text = [
    `Fusion 360 is not reachable at ${host}:${port}.`,
    "Open Fusion and start the 'AutodeskFusionMCP' add-in (Shift+S → Add-Ins tab → Run), then retry.",
    "If Fusion is on another machine set FUSION_MCP_HOST.",
  ].join("\n");
  return toolFailure(text, detail);
}

/**
 * 403 from the add-in: the request reached Fusion but was refused on
 * origin/identity grounds. Reachable-but-refused, so it is NOT tier (c).
 */
export function forbiddenFailure(host: string, port: number, detail?: string): ToolResult {
  const text = [
    `The Fusion add-in at ${host}:${port} rejected the request (HTTP 403).`,
    "The add-in gates on the Origin header, not the host. This bridge always sends the",
    `loopback origin http://127.0.0.1:${port}, which the add-in accepts by default, so`,
    "FUSION_MCP_HOST cannot cause this. A 403 means a non-bridge client (such as a",
    "browser) reached the endpoint, or `allowed_origins` was edited away from its",
    "shipped empty default in the add-in (lib/mcp_server.py).",
  ].join("\n");
  return toolFailure(text, detail);
}

/**
 * 405/406 from the add-in: a contract violation by the bridge itself.
 * Must never happen in a released build, so it is surfaced loudly.
 */
export function bridgeBugFailure(status: number): ToolResult {
  return toolFailure(
    `ai-drawer-mcp bridge bug: upstream answered HTTP ${status}. ` +
      "This should be impossible in a released build. Please report it.",
  );
}

/** Success result carrying plain text. */
export function toolSuccess(...lines: readonly string[]): ToolResult {
  return textResult(lines.join("\n"), false);
}

/** Success result carrying indented JSON (used for structured reports). */
export function toolJson(value: unknown, pretty = true): ToolResult {
  return textResult(JSON.stringify(value, null, pretty ? 2 : 0), false);
}
