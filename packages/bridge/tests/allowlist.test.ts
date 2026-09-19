import { describe, expect, it } from "vitest";
import {
  ALLOWED,
  BLOCKED_HARD,
  denyMessage,
  filterToolList,
  gateToolCall,
  isAllowed,
  isHardBlocked,
  PENDING,
  resetSecuritySink,
  type SecurityEvent,
  setSecuritySink,
} from "../src/allowlist.js";

describe("allowlist", () => {
  it("exposes the reduced Wave-1 surface plus the bridge-owned health probe", () => {
    expect([...ALLOWED].sort()).toEqual(
      [
        "capture_viewport",
        "fetch_api_documentation",
        "fetch_design_guide",
        "fetch_online_documentation",
        "fusion_health",
        "get_active_selection",
        "get_viewport",
        "set_viewport",
      ].sort(),
    );
  });

  it("keeps the Wave-3 CAD surface in PENDING, not in ALLOWED", () => {
    expect(PENDING).toContain("create_sketch");
    expect(PENDING).toContain("extrude");
    expect(PENDING).toContain("fillet");
    expect(PENDING).toContain("hole");
    expect(PENDING).toContain("list_parameters");
    expect(PENDING).toContain("modify_parameter");
    for (const name of PENDING) expect(ALLOWED.has(name)).toBe(false);
  });

  it("lists the raw-capability names that must never be proxied", () => {
    expect([...BLOCKED_HARD].sort()).toEqual(
      ["call_autodesk_api", "delete_scripts", "execute_python", "list_scripts", "load_script", "save_script"].sort(),
    );
  });

  it("admits Wave-1 names and refuses everything else", () => {
    expect(isAllowed("capture_viewport")).toBe(true);
    expect(isAllowed("fusion_health")).toBe(true);
    expect(isAllowed("execute_python")).toBe(false);
    expect(isAllowed("create_sketch")).toBe(false);
    expect(isAllowed("totally_made_up")).toBe(false);
    expect(isHardBlocked("execute_python")).toBe(true);
    expect(isHardBlocked("create_sketch")).toBe(false);
  });

  it("classifies refusals by deny reason", () => {
    expect(gateToolCall("capture_viewport").allowed).toBe(true);
    expect(gateToolCall("execute_python")).toEqual({
      allowed: false,
      name: "execute_python",
      reason: "blocked-hard",
    });
    expect(gateToolCall("extrude")).toEqual({ allowed: false, name: "extrude", reason: "pending-wave3" });
    expect(gateToolCall("nonsense")).toEqual({ allowed: false, name: "nonsense", reason: "not-allowed" });
  });

  it("logs a security event for every refusal", () => {
    const events: SecurityEvent[] = [];
    const previous = setSecuritySink((event) => events.push(event));
    try {
      gateToolCall("execute_python");
      gateToolCall("extrude");
      gateToolCall("nonsense");
    } finally {
      setSecuritySink(previous);
    }
    expect(events.map((event) => event.tool)).toEqual(["execute_python", "extrude", "nonsense"]);
    expect(events.map((event) => event.reason)).toEqual(["blocked-hard", "pending-wave3", "not-allowed"]);
    expect(events.every((event) => event.ts.length > 0)).toBe(true);
  });

  it("filters a proxied tools/list, dropping blocked and unknown names", () => {
    const events: SecurityEvent[] = [];
    const previous = setSecuritySink((event) => events.push(event));
    try {
      const filtered = filterToolList([
        "capture_viewport",
        "get_viewport",
        "execute_python",
        "create_sketch",
        "not_a_real_tool",
      ]);
      expect(filtered).toEqual(["capture_viewport", "get_viewport"]);
    } finally {
      setSecuritySink(previous);
    }
    // Blocked advertisements are logged; Wave-3 and unknown ones are simply absent.
    expect(events.map((event) => event.tool)).toEqual(["execute_python"]);
  });

  it("never forwards a blocked name even if the add-in advertises it", () => {
    for (const name of BLOCKED_HARD) {
      expect(filterToolList([name])).toEqual([]);
      expect(gateToolCall(name).allowed).toBe(false);
    }
  });

  it("produces actionable denial text", () => {
    expect(denyMessage("execute_python", "blocked-hard")).toMatch(/blocked by the ai-drawer-mcp security policy/);
    expect(denyMessage("extrude", "pending-wave3")).toMatch(/not available yet/);
    expect(denyMessage("nope", "not-allowed")).toMatch(/tools\/list/);
  });

  it("restores the default sink", () => {
    const previous = setSecuritySink(() => undefined);
    resetSecuritySink();
    expect(() => setSecuritySink(previous)).not.toThrow();
  });
});
