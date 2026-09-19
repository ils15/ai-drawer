/**
 * Connection state machine for the upstream add-in.
 *
 *   DISCONNECTED ──tools/call──▶ PROBING ──ping ok──▶ CONNECTED
 *        ▲                          │                    │
 *        │ ping failed              │                    │ ECONNREFUSED / timeout
 *        └──────────────────────────┘                    ▼
 *                       tier-(c) error        CONNECTED ──inline retry──▶ PROBING
 *
 * THERE IS NO BACKGROUND POLLING LOOP. OpenCode keeps the bridge spawned for
 * the whole session, so a busy-wait here would burn CPU while the
 * conversation sits idle. State advances only when a request needs the add-in:
 *
 *  - CONNECTED forwards the call. A refused connection or timeout demotes to
 *    PROBING and retries exactly once, inline.
 *  - PROBING issues a single 2s `ping`. Success promotes to CONNECTED and
 *    replays the queued call; failure demotes to DISCONNECTED and returns the
 *    tier-(c) actionable error.
 *  - DISCONNECTED does nothing. The next tools/call performs a lazy probe.
 *  - fusion_health always probes on demand, whatever the current state.
 */

import type { ResolvedHost } from "./config.js";
import type { JsonRpcMessage, JsonRpcRequest } from "./json-rpc.js";
import { asJsonRpcSuccess } from "./json-rpc.js";
import type { UpstreamFailureKind } from "./upstream-client.js";
import { PROTOCOL_VERSION, sendPing, sendUpstream } from "./upstream-client.js";

export type ConnectionState = "DISCONNECTED" | "PROBING" | "CONNECTED";

/** Report returned by the bridge-owned fusion_health tool. */
export interface HealthReport {
  readonly connected: boolean;
  readonly host: string;
  readonly port: number;
  readonly latency_ms: number | null;
  readonly protocol_version: string | null;
  readonly last_error: string | null;
  readonly state: ConnectionState;
}

/** One exchange with the add-in, decoded into the tier the caller maps to a result. */
export type CallOutcome =
  | { readonly ok: true; readonly message: JsonRpcMessage }
  | { readonly ok: false; readonly kind: UpstreamFailureKind; readonly detail: string };

const PING_TIMEOUT_MS = 2_000;
const INITIALIZE_TIMEOUT_MS = 5_000;

/** Monitors one upstream endpoint for the lifetime of the process. */
export class ConnectionMonitor {
  private state: ConnectionState = "DISCONNECTED";
  private nextId = 1;
  private lastError: string | null = null;
  private latencyMs: number | null = null;
  private protocolVersion: string | null = null;
  private initializePromise: Promise<boolean> | null = null;

  /** Number of probes issued. Exposed so tests can prove no busy-waiting. */
  public probeCount = 0;

  constructor(private readonly host: ResolvedHost) {}

  get currentState(): ConnectionState {
    return this.state;
  }

  get endpoint(): ResolvedHost {
    return this.host;
  }

  /** The last recorded failure detail, surfaced through fusion_health. */
  get lastErrorText(): string | null {
    return this.lastError;
  }

  /**
   * Sends a JSON-RPC request, advancing the state machine as needed.
   * Never throws; failures surface as a `kind` for the caller to map.
   */
  async send(request: Omit<JsonRpcRequest, "jsonrpc" | "id">, timeoutMs?: number): Promise<CallOutcome> {
    if (this.state === "CONNECTED") {
      const outcome = await this.forward(request, timeoutMs);
      if (outcome.ok || !isTransient(outcome)) return outcome;

      // CONNECTED but the socket just died: demote and retry once, inline.
      this.setState("PROBING");
      if (!(await this.probe())) return failureOutcome(this.lastError);
      this.setState("CONNECTED");
      return this.forward(request, timeoutMs);
    }

    if (this.state === "PROBING") {
      // Re-entrant during an inline retry: one ping, then replay.
      if (!(await this.probe())) return failureOutcome(this.lastError);
      this.setState("CONNECTED");
      return this.forward(request, timeoutMs);
    }

    // DISCONNECTED: a lazy probe, spent only because a caller needs the add-in.
    this.setState("PROBING");
    if (!(await this.probe())) return failureOutcome(this.lastError);
    this.setState("CONNECTED");
    return this.forward(request, timeoutMs);
  }

  /** Probes the add-in on demand. Used by fusion_health and by tests. */
  async probe(): Promise<boolean> {
    this.probeCount += 1;
    const started = Date.now();
    const result = await sendPing(this.host.host, this.host.port, this.allocateId(), PING_TIMEOUT_MS);
    const latency = Date.now() - started;

    if (result.ok) {
      this.recordSuccess(latency);
      return true;
    }
    this.recordFailure(result.kind, result.detail);
    return false;
  }

  /**
   * Performs the one-time upstream initialize at startup.
   *
   * Best-effort: a Fusion that is closed or whose add-in is not started is
   * not fatal. On success the negotiated protocol version is recorded so
   * fusion_health can report what the add-in actually speaks.
   */
  async initialize(): Promise<boolean> {
    this.initializePromise = this.runInitialize();
    return this.initializePromise;
  }

  /**
   * Records the negotiated protocol version once the startup exchange settles.
   * Called through {@link initialize} so {@link health} can join the result.
   */
  private async runInitialize(): Promise<boolean> {
    const result = await this.send(
      {
        method: "initialize",
        params: {
          protocolVersion: PROTOCOL_VERSION,
          capabilities: {},
          clientInfo: { name: "ai-drawer-mcp", version: "0.1.0" },
        },
      },
      INITIALIZE_TIMEOUT_MS,
    );

    if (!result.ok) return false;
    const success = asJsonRpcSuccess(result.message);
    const version = (success?.result as { protocolVersion?: unknown } | null)?.protocolVersion;
    if (typeof version === "string") this.protocolVersion = version;
    return true;
  }

  /**
   * Answers fusion_health. Always probes live, even when CONNECTED, so the
   * report reflects reality rather than a stale cached state.
   */
  async health(): Promise<HealthReport> {
    // Wait for the startup initialize to settle before reporting. It is
    // best-effort and never rejects, but joining it is what makes
    // protocol_version reflect what the add-in actually speaks rather than
    // racing the startup exchange.
    if (this.initializePromise !== null) await this.initializePromise;
    const reachable = await this.probe();
    return {
      connected: reachable,
      host: this.host.host,
      port: this.host.port,
      latency_ms: reachable ? this.latencyMs : null,
      protocol_version: reachable ? this.protocolVersion : null,
      last_error: this.lastError,
      state: this.state,
    };
  }

  private async forward(request: Omit<JsonRpcRequest, "jsonrpc" | "id">, timeoutMs?: number): Promise<CallOutcome> {
    const result = await sendUpstream(
      this.host.host,
      this.host.port,
      { jsonrpc: "2.0", id: this.allocateId(), ...request },
      timeoutMs,
    );
    if (result.ok) {
      this.markHealthy();
      return { ok: true, message: result.message };
    }
    this.recordFailure(result.kind, result.detail);
    return { ok: false, kind: result.kind, detail: result.detail };
  }

  private recordSuccess(latency: number): void {
    this.latencyMs = latency;
    this.lastError = null;
    this.setState("CONNECTED");
  }

  private markHealthy(): void {
    this.lastError = null;
    this.setState("CONNECTED");
  }

  private recordFailure(kind: UpstreamFailureKind, detail: string): void {
    this.lastError = `${kind}: ${detail}`;
    this.latencyMs = null;
    this.setState("DISCONNECTED");
  }

  private setState(next: ConnectionState): void {
    this.state = next;
  }

  private allocateId(): number {
    const id = this.nextId;
    this.nextId += 1;
    return id;
  }
}

/** A failure that justifies demoting a CONNECTED session to PROBING. */
function isTransient(outcome: { ok: false; kind: UpstreamFailureKind }): boolean {
  return outcome.kind === "unreachable" || outcome.kind === "timeout";
}

/** Builds the tier-(c) outcome the caller maps to actionable text. */
function failureOutcome(lastError: string | null): CallOutcome {
  return { ok: false, kind: "unreachable", detail: lastError ?? "add-in not reachable" };
}
