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
  it("exposes the live surface plus the bridge-owned health probe", () => {
    expect([...ALLOWED].sort()).toEqual(
      [
        "add_parameter",
        "apply_appearance",
        "capture_viewport",
        "chamfer",
        "circular_pattern",
        "close_document",
        "create_body",
        "create_component",
        "create_sketch",
        "extrude",
        "export_document",
        "fetch_api_documentation",
        "fetch_design_guide",
        "fetch_online_documentation",
        "fillet",
        "fusion_diagnostics",
        "fusion_health",
        "fusion_status",
        "get_active_selection",
        "get_document_info",
        "get_viewport",
        "hole",
        "inspect_entity",
        "list_bodies",
        "list_documents",
        "list_features",
        "list_parameters",
        "list_tool_categories",
        "measure",
        "modify_parameter",
        "new_document",
        "open_document",
        "rectangular_pattern",
        "revolve",
        "save_document",
        "set_viewport",
      ].sort(),
    );
  });

  it("promoted the Wave-3b CAD surface out of PENDING into ALLOWED", () => {
    expect(PENDING).toEqual([]);
    const wave3b = ["create_sketch", "extrude", "revolve", "create_component", "create_body", "apply_appearance"];
    for (const name of wave3b) expect(ALLOWED.has(name)).toBe(true);
  });

  it("promoted the Wave-4 read-only inspection surface out of PENDING into ALLOWED", () => {
    expect(PENDING).toEqual([]);
    const wave4 = ["list_bodies", "inspect_entity", "list_features", "measure"];
    for (const name of wave4) {
      expect(ALLOWED.has(name)).toBe(true);
      expect(PENDING.includes(name)).toBe(false);
    }
  });

  it("promoted the Wave-2 lifecycle, document and parameter tools out of PENDING", () => {
    const wave2 = [
      "fusion_status",
      "list_documents",
      "new_document",
      "open_document",
      "save_document",
      "export_document",
      "close_document",
      "get_document_info",
      "list_parameters",
      "add_parameter",
      "modify_parameter",
    ];
    for (const name of wave2) {
      expect(ALLOWED.has(name)).toBe(true);
      expect(PENDING.includes(name)).toBe(false);
    }
  });

  it("lists the raw-capability names that must never be proxied", () => {
    expect([...BLOCKED_HARD].sort()).toEqual(
      ["call_autodesk_api", "delete_scripts", "execute_python", "list_scripts", "load_script", "save_script"].sort(),
    );
  });

  it("admits Wave-1, Wave-3b and Wave-4 names and refuses everything else", () => {
    expect(isAllowed("capture_viewport")).toBe(true);
    expect(isAllowed("fusion_health")).toBe(true);
    expect(isAllowed("create_sketch")).toBe(true);
    expect(isAllowed("apply_appearance")).toBe(true);
    expect(isAllowed("measure")).toBe(true);
    expect(isAllowed("execute_python")).toBe(false);
    expect(isAllowed("apply_material")).toBe(false);
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
    expect(gateToolCall("extrude")).toEqual({ allowed: true, name: "extrude" });
    expect(gateToolCall("apply_material")).toEqual({
      allowed: false,
      name: "apply_material",
      reason: "not-allowed",
    });
    expect(gateToolCall("nonsense")).toEqual({ allowed: false, name: "nonsense", reason: "not-allowed" });
  });

  it("logs a security event for every refusal", () => {
    const events: SecurityEvent[] = [];
    const previous = setSecuritySink((event) => events.push(event));
    try {
      gateToolCall("execute_python");
      gateToolCall("apply_material");
      gateToolCall("nonsense");
    } finally {
      setSecuritySink(previous);
    }
    expect(events.map((event) => event.tool)).toEqual(["execute_python", "apply_material", "nonsense"]);
    expect(events.map((event) => event.reason)).toEqual(["blocked-hard", "not-allowed", "not-allowed"]);
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
        "apply_material",
        "not_a_real_tool",
      ]);
      expect(filtered).toEqual(["capture_viewport", "get_viewport"]);
    } finally {
      setSecuritySink(previous);
    }
    // Blocked advertisements are logged; retired and unknown ones are simply absent.
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
