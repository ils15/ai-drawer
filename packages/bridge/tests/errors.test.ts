/**
 * Remediation text for the failure tiers. The wording is the user-facing
 * contract, so it is asserted verbatim against the source behavior it describes.
 */

import { describe, expect, it } from "vitest";
import { bridgeBugFailure, forbiddenFailure, unreachableFailure } from "../src/errors.js";

describe("forbiddenFailure (HTTP 403)", () => {
  it("names the endpoint that rejected the request", () => {
    const result = forbiddenFailure("127.0.0.1", 6111);
    expect(result.isError).toBe(true);
    expect(result.content).toHaveLength(1);
    const text = result.content[0]?.text ?? "";
    expect(text).toContain("The Fusion add-in at 127.0.0.1:6111 rejected the request (HTTP 403).");
  });

  it("attributes the gate to the Origin header, not a host allowlist", () => {
    const text = forbiddenFailure("127.0.0.1", 6111).content[0]?.text ?? "";
    expect(text).toContain("The add-in gates on the Origin header, not the host.");
  });

  it("names the fixed loopback origin the bridge always sends", () => {
    const text = forbiddenFailure("127.0.0.1", 6111).content[0]?.text ?? "";
    expect(text).toContain("loopback origin http://127.0.0.1:6111");
  });

  it("states that FUSION_MCP_HOST cannot cause a 403", () => {
    const text = forbiddenFailure("127.0.0.1", 6111).content[0]?.text ?? "";
    expect(text).toContain("FUSION_MCP_HOST cannot cause this.");
  });

  it("points at the two real causes instead of the pinned-host dead end", () => {
    const text = forbiddenFailure("127.0.0.1", 6111).content[0]?.text ?? "";
    expect(text).toContain("a non-bridge client");
    expect(text).toContain("allowed_origins");
    expect(text).toContain("lib/mcp_server.py");
    expect(text).not.toContain("make sure it matches the host");
  });

  it("appends the upstream detail when provided", () => {
    const text = forbiddenFailure("127.0.0.1", 6111, "upstream rejected the request").content[0]?.text ?? "";
    expect(text).toContain("upstream rejected the request");
  });
});

describe("sibling tiers keep their distinct contracts", () => {
  it("unreachableFailure stays an actionable tier-(c) message", () => {
    const text = unreachableFailure("127.0.0.1", 6111).content[0]?.text ?? "";
    expect(text).toContain("Fusion 360 is not reachable at 127.0.0.1:6111.");
    expect(text).toContain("FUSION_MCP_HOST");
  });

  it("bridgeBugFailure reports 405/406 as impossible-in-release", () => {
    const text = bridgeBugFailure(406).content[0]?.text ?? "";
    expect(text).toContain("HTTP 406");
    expect(text).toContain("should be impossible in a released build");
  });
});
