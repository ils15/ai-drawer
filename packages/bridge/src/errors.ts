/**
 * Structured error envelope: the one shape every bridge failure takes.
 *
 * Every failure the LLM can observe leaves the bridge as a tool result whose
 * `content[0].text` is JSON — the same envelope the add-in's
 * `fusion_bridge/errors.py` `structured_error` emits, so a client can branch on
 * a single field regardless of which side produced the error:
 *
 *   error_kind — a stable name from BRIDGE_ERROR_KINDS. It says WHERE the
 *                failure happened and whether retrying can help.
 *   message    — what went wrong, in user-facing terms.
 *   hint       — one actionable next step that usually resolves it. Never empty.
 *
 * The three tiers stay distinct, and are now told apart by kind rather than by
 * tone of voice:
 *
 *  (a) JSON-RPC protocol error — the request itself was malformed or
 *      unsupported. Returned as a real JSON-RPC error object so the client
 *      knows the server (not the tool) rejected it. Never an envelope: it does
 *      not travel inside a tool result.
 *
 *  (b) Tool execution failure  — the add-in answered, but the tool failed. The
 *      add-in's own envelopes pass through mapToolResult unchanged; a failure
 *      the bridge has to synthesize on this tier carries `tool_failed`.
 *
 *  (c) Add-in unreachable      — Fusion or the add-in is not running. A
 *      synthesized envelope naming the exact endpoint that was tried.
 *
 * Exception messages, stack traces and internal identifiers never enter the
 * envelope; that detail stays in logs. Keeping the taxonomy in one module is
 * what stops the bridge and the add-in from drifting apart on error names — a
 * kind added here is the only place a new bridge failure category may appear.
 */

import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { type DenyReason, denyMessage } from "./allowlist.js";
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
 * This IS the SDK's CallToolResult: a bridge tool result is an MCP tool result,
 * so handlers return them with no cast. `isError` distinguishes tiers (b) and
 * (c) from a genuine success.
 */
export type ToolResult = CallToolResult;

/**
 * The kinds the bridge itself can emit. The add-in's own kinds
 * (no_active_document, invalid_expression, ...) surface unchanged through
 * mapToolResult and deliberately have no twin here: a bridge kind describes a
 * failure the bridge owns or detected at the wire, never a Fusion-level one.
 */
export const BRIDGE_ERROR_KINDS = [
  // Security gate: the name can never be proxied.
  "blocked_hard",
  // Security gate: the name is not on the curated surface (unknown tool).
  "not_allowed",
  // Security gate: a Wave-3 roadmap tool, not enabled yet.
  "pending_wave3",
  // zod rejected the arguments before they crossed the wire.
  "invalid_arguments",
  // Tier (b): the add-in answered, but the tool failed.
  "tool_failed",
  // Tier (c): connection refused / host down.
  "addin_unreachable",
  // The request outlived its budget; the call may still be running.
  "addin_timeout",
  // HTTP 403: reachable but refused on origin/identity grounds.
  "addin_forbidden",
  // 405/406: the bridge violated its own wire contract. Never happens.
  "bridge_bug",
  // The upstream reply could not be decoded into a tool result.
  "protocol_error",
] as const;

export type BridgeErrorKind = (typeof BRIDGE_ERROR_KINDS)[number];

const KIND_INDEX: ReadonlySet<string> = new Set<string>(BRIDGE_ERROR_KINDS);

/** The JSON payload inside `content[0].text` of a bridge error result. */
export interface ErrorEnvelope {
  readonly error_kind: BridgeErrorKind;
  readonly message: string;
  readonly hint: string;
}

/**
 * One validation problem, as reported by zod. Structural on purpose: errors.ts
 * stays independent of the schema library, and zod's issues satisfy this shape.
 */
export interface ValidationIssue {
  readonly path: readonly PropertyKey[];
  readonly message: string;
}

/** Default user-facing messages; a call site that knows only the kind still says something useful. */
const DEFAULT_MESSAGES: Record<BridgeErrorKind, string> = {
  blocked_hard: "The tool is blocked by the ai-drawer-mcp security policy and can never be called.",
  not_allowed: "The tool is not exposed by this bridge.",
  pending_wave3: "The tool is not available yet (Wave-3 surface).",
  invalid_arguments: "The arguments do not match the tool schema.",
  tool_failed: "The tool failed inside Fusion.",
  addin_unreachable: "Fusion 360 is not reachable.",
  addin_timeout: "Fusion did not answer in time.",
  addin_forbidden: "The Fusion add-in rejected the request (HTTP 403).",
  bridge_bug: "The bridge hit an internal contract violation.",
  protocol_error: "The add-in sent a reply the bridge could not decode.",
};

/** Default hints: one actionable step per kind. Never empty. */
const DEFAULT_HINTS: Record<BridgeErrorKind, string> = {
  blocked_hard:
    "This refusal is intentional and permanent. Call tools/list for the curated surface; " +
    "no argument form bypasses it.",
  not_allowed:
    "Call tools/list to see the available tools; the name may be misspelled or served by a different bridge.",
  pending_wave3:
    "This tool is on the roadmap but not enabled. Use an available tool that reaches the same goal instead.",
  invalid_arguments: "Compare every argument against the tool's input schema, correct the failing fields, and retry.",
  tool_failed:
    "Read the message: it says what the tool could not do. Fix the named cause and retry; " +
    "if it repeats, call fusion_health.",
  addin_unreachable:
    "Open Fusion and start the 'AutodeskFusionMCP' add-in (Shift+S → Add-Ins tab → Run), then retry. " +
    "If Fusion is on another machine set FUSION_MCP_HOST.",
  addin_timeout:
    "The call may still be running inside Fusion. Wait a moment and retry; if it repeats, simplify the " +
    "request or restart the add-in.",
  addin_forbidden:
    "A 403 is an origin refusal, not an outage. Check that only this bridge reaches the endpoint and that " +
    "allowed_origins in the add-in (lib/mcp_server.py) keeps its shipped empty default.",
  bridge_bug:
    "Restart the bridge and retry. If it repeats, report the message: the bridge and the add-in disagree on " +
    "the wire contract.",
  protocol_error:
    "Retry once. If it repeats, restart the add-in: it answered with a shape the bridge cannot map to a tool result.",
};

/** Maps each allowlist refusal reason onto its envelope kind. */
const GATE_KINDS: Record<DenyReason, BridgeErrorKind> = {
  "blocked-hard": "blocked_hard",
  "not-allowed": "not_allowed",
  "pending-wave3": "pending_wave3",
};

/** Tier (a) — builds a JSON-RPC protocol error object. */
export function protocolError(code: number, message: string, data?: unknown): JsonRpcErrorBody {
  return data === undefined ? { code, message } : { code, message, data };
}

/** The single constructor every text result shares, so tiers never drift in shape. */
function textResult(text: string, isError: boolean): ToolResult {
  return { content: [{ type: "text", text }], isError };
}

/** True only for a non-empty string; narrows away undefined/null. */
function nonEmpty(value: string | undefined | null): value is string {
  return typeof value === "string" && value.length > 0;
}

/**
 * Builds one structured error envelope. Every failure constructor delegates
 * here, so a bridge error is always the same three fields in the same order the
 * add-in emits them.
 *
 * An unrecognized kind degrades to `bridge_bug` instead of raising — a bad
 * error name must never become a second failure while reporting one.
 */
export function structuredError(kind: BridgeErrorKind, message?: string, hint?: string): ToolResult {
  const resolved = KIND_INDEX.has(kind) ? kind : "bridge_bug";
  const envelope: ErrorEnvelope = {
    error_kind: resolved,
    message: nonEmpty(message) ? message : DEFAULT_MESSAGES[resolved],
    hint: nonEmpty(hint) ? hint : DEFAULT_HINTS[resolved],
  };
  return textResult(JSON.stringify(envelope, null, 2), true);
}

/** Security gate: the tool name was refused before any argument was read. */
export function gateFailure(name: string, reason: DenyReason): ToolResult {
  return structuredError(GATE_KINDS[reason], denyMessage(name, reason));
}

/**
 * zod rejected the arguments. The hint lists every offending field path so the
 * LLM can correct the arguments without re-reading the whole schema; the message
 * names the tool. Only zod's own issue messages are carried — never a stack.
 */
export function invalidArguments(name: string, issues: readonly ValidationIssue[]): ToolResult {
  const detail = issues
    .map((issue) => `${issue.path.length === 0 ? name : issue.path.join(".")}: ${issue.message}`)
    .join("; ");
  return structuredError(
    "invalid_arguments",
    `Invalid arguments for '${name}'.`,
    nonEmpty(detail) ? detail : DEFAULT_HINTS.invalid_arguments,
  );
}

/** Tier (b) — the add-in answered, but the tool failed. */
export function toolFailure(kind: BridgeErrorKind, message?: string, hint?: string): ToolResult {
  return structuredError(kind, message, hint);
}

/**
 * Tier (c) — Fusion is unreachable. The message names the endpoint actually
 * attempted, per the bridge contract, so the hint can stay a single action.
 */
export function unreachableFailure(host: string, port: number, detail?: string): ToolResult {
  const base = `Fusion 360 is not reachable at ${host}:${port}.`;
  return structuredError("addin_unreachable", nonEmpty(detail) ? `${base} ${detail}` : base);
}

/** The request outlived its budget; the call may still be running inside Fusion. */
export function timeoutFailure(host: string, port: number, timeoutMs: number, detail?: string): ToolResult {
  const base = `Fusion 360 at ${host}:${port} did not answer within ${timeoutMs} ms.`;
  return structuredError("addin_timeout", nonEmpty(detail) ? `${base} ${detail}` : base);
}

/**
 * 403 from the add-in: the request reached Fusion but was refused on
 * origin/identity grounds. Reachable-but-refused, so it is NOT tier (c).
 */
export function forbiddenFailure(host: string, port: number, detail?: string): ToolResult {
  const base = [
    `The Fusion add-in at ${host}:${port} rejected the request (HTTP 403).`,
    "The add-in gates on the Origin header, not the host. This bridge always sends the",
    `loopback origin http://127.0.0.1:${port}, which the add-in accepts by default, so`,
    "FUSION_MCP_HOST cannot cause this. A 403 means a non-bridge client (such as a",
    "browser) reached the endpoint, or `allowed_origins` was edited away from its",
    "shipped empty default in the add-in (lib/mcp_server.py).",
  ].join(" ");
  return structuredError("addin_forbidden", nonEmpty(detail) ? `${base} ${detail}` : base);
}

/**
 * 405/406 from the add-in: a contract violation by the bridge itself. Must
 * never happen in a released build, so it is surfaced loudly. The upstream
 * detail names the real status and endpoint that triggered it.
 */
export function bridgeBugFailure(detail?: string): ToolResult {
  const base =
    "ai-drawer-mcp bridge bug: the add-in answered with an HTTP status the wire contract forbids " +
    "(405/406). This should be impossible in a released build. Please report it.";
  return structuredError("bridge_bug", nonEmpty(detail) ? `${base} ${detail}` : base);
}

/** The upstream reply could not be turned into a tool result. */
export function protocolFailure(name: string, detail?: string): ToolResult {
  const base = `Tool '${name}' returned a reply the bridge could not decode.`;
  return structuredError("protocol_error", nonEmpty(detail) ? `${base} ${detail}` : base);
}

/** Success result carrying plain text. */
export function toolSuccess(...lines: readonly string[]): ToolResult {
  return textResult(lines.join("\n"), false);
}

/** Success result carrying indented JSON (used for structured reports). */
export function toolJson(value: unknown, pretty = true): ToolResult {
  return textResult(JSON.stringify(value, null, pretty ? 2 : 0), false);
}
