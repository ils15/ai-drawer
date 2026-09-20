/**
 * Runtime behavior of list_tool_categories: the bridge-owned listing that
 * publishes the live surface grouped by category.
 *
 * The static classification map (CATEGORY_BY_TOOL) is pinned against the add-in
 * artifact by tests/drift-guard.test.ts. This file tests the DERIVED listing —
 * what an LLM actually receives — and the guarantee that a tool which is not
 * live can never appear in it, even by accident.
 */

import { expect, it } from "vitest";
import { ALLOWED, BLOCKED_HARD, CATEGORY_TOOL, HEALTH_TOOL, PENDING } from "../src/allowlist.js";
import {
  CATEGORY_BY_TOOL,
  categoryTool,
  listToolCategories,
  TOOL_CATEGORIES,
  type ToolCategoriesReport,
} from "../src/categories.js";

/** Every tool name the listing reports, across all categories. */
function listedTools(report: ToolCategoriesReport): string[] {
  return report.categories.flatMap((category) => category.tools);
}

it("list_tool_categories is itself part of the live surface", () => {
  expect(ALLOWED.has(CATEGORY_TOOL)).toBe(true);
});

it("reports the whole live surface exactly once", () => {
  const report = listToolCategories();

  expect(report.total_tools).toBe(32);
  expect(report.total_tools).toBe(ALLOWED.size);

  const tools = listedTools(report);
  // No duplicates: every live tool sits in exactly one category.
  expect(tools).toHaveLength(ALLOWED.size);
  expect(new Set(tools).size).toBe(tools.length);
  // The union of the per-category lists IS the live surface, nothing more.
  expect(new Set(tools)).toEqual(new Set(ALLOWED));
});

it("uses the closed category set the add-in declares, in order", () => {
  const report = listToolCategories();

  expect(report.categories.map((category) => category.name)).toEqual([...TOOL_CATEGORIES]);
  for (const category of report.categories) {
    expect(category.description.length).toBeGreaterThan(0);
  }
});

it("classifies every live tool inside that closed set", () => {
  for (const category of Object.values(CATEGORY_BY_TOOL)) {
    expect((TOOL_CATEGORIES as readonly string[]).includes(category)).toBe(true);
  }
  // Nothing live is left unclassified: that would drop it from the listing.
  for (const name of ALLOWED) {
    expect(CATEGORY_BY_TOOL[name]).toBeDefined();
  }
});

it("keeps the PENDING roadmap empty now that the Wave-3b CAD surface is live", () => {
  const tools = listedTools(listToolCategories());

  // The Wave-3b tools are promoted into ALLOWED, so nothing sits in PENDING.
  // The list is kept as the promotion slot for the next wave; anything still in
  // it must stay unlisted and unclassified.
  expect(PENDING).toEqual([]);
  for (const name of PENDING) {
    expect(ALLOWED.has(name)).toBe(false);
    expect(tools).not.toContain(name);
    expect(CATEGORY_BY_TOOL[name]).toBeUndefined();
  }
});

it("never surfaces BLOCKED_HARD raw-capability names in any category", () => {
  const tools = listedTools(listToolCategories());

  expect(BLOCKED_HARD.has("execute_python")).toBe(true);
  for (const name of BLOCKED_HARD) {
    expect(ALLOWED.has(name)).toBe(false);
    expect(tools).not.toContain(name);
    expect(CATEGORY_BY_TOOL[name]).toBeUndefined();
  }
});

it("groups the bridge-owned helpers under diagnostics", () => {
  const diagnostics = listToolCategories()
    .categories.find((category) => category.name === "diagnostics")
    ?.tools.sort();

  expect(diagnostics).toContain(HEALTH_TOOL);
  expect(diagnostics).toContain(CATEGORY_TOOL);
});

it("advises the tool listing with an empty, argument-free schema", () => {
  const tool = categoryTool();

  expect(tool.name).toBe(CATEGORY_TOOL);
  expect(tool.description.length).toBeGreaterThan(0);
  expect(tool.inputSchema).toEqual({ type: "object", properties: {} });
});
