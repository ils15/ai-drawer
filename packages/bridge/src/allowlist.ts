/**
 * SECURITY CORE — the curated tool surface.
 *
 * The add-in inside Fusion is fully capable of arbitrary code execution
 * (execute_python and friends). This module is the only thing standing between
 * an LLM prompt-injection and a Python interpreter on the user's machine.
 *
 * INVARIANTS
 *  - tools/list is filtered through ALLOWED. Anything not listed is invisible.
 *  - tools/call is rejected unless the name is in ALLOWED.
 *  - BLOCKED_HARD names are never reachable, and attempts are logged.
 *  - Enabling a tool later is a ONE-LINE change: add the name to ALLOWED.
 *  - PENDING is documentation-only. It is NOT consulted to admit a call.
 */

/** Bridge-owned health probe; answered locally, never forwarded upstream. */
export const HEALTH_TOOL = "fusion_health" as const;

/**
 * Wave-1 reduced surface: the viewport / selection / documentation tools the
 * add-in serves today, plus the bridge-owned health probe.
 *
 * To enable a Wave-3 tool, move its name out of PENDING into this set.
 * Nothing else in the codebase needs to change.
 */
export const ALLOWED: ReadonlySet<string> = new Set<string>([
  "capture_viewport",
  "get_viewport",
  "set_viewport",
  "get_active_selection",
  "fetch_api_documentation",
  "fetch_online_documentation",
  "fetch_design_guide",
  HEALTH_TOOL,
]);

/**
 * Wave-3 CAD tool names the add-in does not serve yet. Listed so that
 * enabling them later is a one-line change and so reviewers can see the
 * roadmap. Deliberately NOT callable today.
 */
export const PENDING: readonly string[] = [
  "create_sketch",
  "extrude",
  "fillet",
  "hole",
  "list_parameters",
  "modify_parameter",
  "create_component",
  "create_body",
  "revolve",
  "apply_material",
  "export_document",
  "save_document",
];

/**
 * Names that must NEVER be proxied, regardless of what the add-in advertises.
 * These are the raw-capability footguns: exposing them would turn the bridge
 * into a remote code execution channel.
 */
export const BLOCKED_HARD: ReadonlySet<string> = new Set<string>([
  "execute_python",
  "call_autodesk_api",
  "save_script",
  "load_script",
  "list_scripts",
  "delete_scripts",
]);

/** Why the gate refused a tool name. */
export type DenyReason = "blocked-hard" | "not-allowed" | "pending-wave3";

/** Outcome of consulting the gate for a tools/call. */
export interface GateDecision {
  readonly allowed: boolean;
  readonly name: string;
  readonly reason?: DenyReason;
}

/** True only for names on the Wave-1 surface. */
export function isAllowed(name: string): boolean {
  return ALLOWED.has(name);
}

/** True for names that must never be forwarded. */
export function isHardBlocked(name: string): boolean {
  return BLOCKED_HARD.has(name);
}

/**
 * The tools/call gate. Consult this for EVERY incoming tool call before doing
 * anything else with the arguments.
 *
 * Returns `{allowed: true}` for the Wave-1 surface, otherwise a refusal
 * carrying the deny reason. Refusals are recorded as security events.
 */
export function gateToolCall(name: string): GateDecision {
  if (ALLOWED.has(name)) return { allowed: true, name };
  if (BLOCKED_HARD.has(name)) {
    logSecurityEvent(name, "blocked-hard");
    return { allowed: false, name, reason: "blocked-hard" };
  }
  if (PENDING.includes(name)) {
    logSecurityEvent(name, "pending-wave3");
    return { allowed: false, name, reason: "pending-wave3" };
  }
  logSecurityEvent(name, "not-allowed");
  return { allowed: false, name, reason: "not-allowed" };
}

/**
 * Filters a proxied tools/list down to the allowed surface.
 * BLOCKED_HARD entries are dropped and logged, so a misbehaving or hostile
 * add-in advertisement can never silently widen the surface.
 */
export function filterToolList(names: readonly string[]): readonly string[] {
  const kept: string[] = [];
  for (const name of names) {
    if (BLOCKED_HARD.has(name)) {
      logSecurityEvent(name, "blocked-hard");
      continue;
    }
    if (ALLOWED.has(name)) kept.push(name);
  }
  return kept;
}

/** Human-readable explanation for a refusal, addressed to the LLM. */
export function denyMessage(name: string, reason: DenyReason): string {
  switch (reason) {
    case "blocked-hard":
      return `Tool '${name}' is blocked by the ai-drawer-mcp security policy and can never be called.`;
    case "pending-wave3":
      return `Tool '${name}' is not available yet (Wave-3 surface). It exists on the roadmap but is not enabled.`;
    default:
      return `Tool '${name}' is not exposed by this bridge. Call tools/list to see the available tools.`;
  }
}

/** One recorded refusal. */
export interface SecurityEvent {
  readonly ts: string;
  readonly tool: string;
  readonly reason: DenyReason;
  readonly kind: "tool-call-blocked" | "tool-list-filtered";
}

/** Security event sink. Overridable in tests; defaults to stderr. */
export type SecuritySink = (event: SecurityEvent) => void;

let securitySink: SecuritySink = defaultSecuritySink;

/** Replaces the security sink (tests). Returns the previous sink. */
export function setSecuritySink(sink: SecuritySink): SecuritySink {
  const previous = securitySink;
  securitySink = sink;
  return previous;
}

/** Restores the default stderr sink. */
export function resetSecuritySink(): void {
  securitySink = defaultSecuritySink;
}

function defaultSecuritySink(event: SecurityEvent): void {
  // stderr only: stdout belongs to the stdio MCP transport.
  console.error(`[ai-drawer-mcp][security] ${JSON.stringify(event)}`);
}

function logSecurityEvent(tool: string, reason: DenyReason): void {
  securitySink({ ts: new Date().toISOString(), tool, reason, kind: "tool-call-blocked" });
}
