/**
 * Public surface of the ai-drawer-mcp bridge.
 *
 * Consumers normally run this package as a stdio server through the
 * `ai-drawer-mcp` bin. These exports exist for embedding and for tests.
 */

export type { DenyReason, GateDecision, SecurityEvent, SecuritySink } from "./allowlist.js";
export {
  ALLOWED,
  BLOCKED_HARD,
  filterToolList,
  gateToolCall,
  isAllowed,
  isHardBlocked,
  PENDING,
  resetSecuritySink,
  setSecuritySink,
} from "./allowlist.js";
export type { HostSource, ResolvedHost } from "./config.js";
export { isWsl, probeHost, resetResolvedHost, resolveHost } from "./config.js";
export type { CallOutcome, ConnectionState, HealthReport } from "./connection.js";
export { ConnectionMonitor } from "./connection.js";
export type {
  BridgeErrorKind,
  ErrorEnvelope,
  TextContent,
  ToolResult,
  ValidationIssue,
} from "./errors.js";
export {
  BRIDGE_ERROR_KINDS,
  bridgeBugFailure,
  forbiddenFailure,
  gateFailure,
  invalidArguments,
  protocolFailure,
  structuredError,
  timeoutFailure,
  toolFailure,
  toolJson,
  toolSuccess,
  unreachableFailure,
} from "./errors.js";
export { createBridgeServer, runStdio } from "./server.js";
export type { UpstreamFailureKind, UpstreamResult } from "./upstream-client.js";
export { extractMessage, PROTOCOL_VERSION, sendPing, sendUpstream } from "./upstream-client.js";
