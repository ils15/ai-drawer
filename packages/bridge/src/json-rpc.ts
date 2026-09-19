/**
 * JSON-RPC 2.0 message model for the upstream (add-in) direction.
 *
 * The bridge speaks two wire protocols:
 *  - stdio JSON-RPC with the LLM client, handled by the MCP SDK
 *  - Streamable-HTTP JSON-RPC with the add-in running inside Fusion
 *
 * These types describe the add-in direction only. They are hand-written
 * rather than imported from the SDK so the proxy can stay tolerant of
 * upstream additions without an `any` escape hatch, and so the narrowers
 * below are unit-testable in isolation.
 */

/** A request the bridge sends upstream to the Fusion add-in. */
export interface JsonRpcRequest {
  readonly jsonrpc: "2.0";
  readonly id: number;
  readonly method: string;
  readonly params?: Readonly<Record<string, unknown>>;
}

/** JSON-RPC success response. `result` is `unknown`: each caller decodes its own shape. */
export interface JsonRpcSuccess {
  readonly jsonrpc: "2.0";
  readonly id: number;
  readonly result: unknown;
}

/** Tier (a) payload — the JSON-RPC error object itself. */
export interface JsonRpcErrorBody {
  readonly code: number;
  readonly message: string;
  readonly data?: unknown;
}

/** JSON-RPC error response. */
export interface JsonRpcErrorResponse {
  readonly jsonrpc: "2.0";
  readonly id: number;
  readonly error: JsonRpcErrorBody;
}

/** Any JSON-RPC response the add-in may return. */
export type JsonRpcMessage = JsonRpcSuccess | JsonRpcErrorResponse;

/** Narrows a decoded value to a JSON-RPC success response, or null. */
export function asJsonRpcSuccess(parsed: unknown): JsonRpcSuccess | null {
  if (!isObject(parsed)) return null;
  if (parsed.jsonrpc !== "2.0") return null;
  if (!hasId(parsed)) return null;
  if (!Object.hasOwn(parsed, "result")) return null;
  return { jsonrpc: "2.0", id: parsed.id, result: parsed.result };
}

/** Narrows a decoded value to a JSON-RPC error response, or null. */
export function asJsonRpcError(parsed: unknown): JsonRpcErrorResponse | null {
  if (!isObject(parsed)) return null;
  if (parsed.jsonrpc !== "2.0") return null;
  if (!hasId(parsed)) return null;
  const error = parsed.error;
  if (!isObject(error)) return null;
  if (typeof error.code !== "number" || typeof error.message !== "string") return null;
  return {
    jsonrpc: "2.0",
    id: parsed.id,
    error: { code: error.code, message: error.message, data: error.data },
  };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasId(value: Record<string, unknown>): value is Record<string, unknown> & { id: number } {
  return typeof value.id === "number";
}
