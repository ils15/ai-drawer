/**
 * Tool categories — the closed set the add-in declares, mirrored on the bridge.
 *
 * The add-in classifies every tool it serves into exactly one category
 * (CATEGORY_* in packages/addin/fusion_bridge/tool_surface.py). This module is
 * the bridge's mirror of that classification, plus the bridge-owned tool that
 * publishes it. The cross-package drift guard in tests/drift-guard.test.ts pins
 * the two together, so a tool added on one side without the other fails the
 * build.
 *
 * INVARIANTS
 *  - every live tool is classified exactly once, in the closed set below;
 *  - the listing is derived from ALLOWED at call time, so a tool that is not
 *    live can never appear, even if it is classified here;
 *  - PENDING and BLOCKED_HARD names are never classified, so they can never be
 *    surfaced by list_tool_categories.
 */

import type { Tool } from "@modelcontextprotocol/sdk/types.js";
import { ALLOWED, CATEGORY_TOOL, HEALTH_TOOL } from "./allowlist.js";

/** The bridge-owned category listing tool; answered locally, never forwarded. */
export { CATEGORY_TOOL };

/**
 * The closed set of categories. A tool belongs to exactly one; the drift guard
 * rejects a classification outside this list.
 */
export const TOOL_CATEGORIES = [
  "viewport",
  "selection",
  "documents",
  "parameters",
  "documentation",
  "diagnostics",
] as const;

export type ToolCategory = (typeof TOOL_CATEGORIES)[number];

/**
 * The classification of the whole live surface. Add-in tools mirror the
 * `category` field the add-in declares; the two bridge-owned helpers sit under
 * diagnostics, the only observability bucket in the set.
 */
export const CATEGORY_BY_TOOL: Readonly<Record<string, ToolCategory>> = {
  // viewport
  capture_viewport: "viewport",
  get_viewport: "viewport",
  set_viewport: "viewport",
  // selection
  get_active_selection: "selection",
  // documentation
  fetch_api_documentation: "documentation",
  fetch_online_documentation: "documentation",
  fetch_design_guide: "documentation",
  // documents
  list_documents: "documents",
  new_document: "documents",
  open_document: "documents",
  save_document: "documents",
  export_document: "documents",
  close_document: "documents",
  get_document_info: "documents",
  // parameters
  list_parameters: "parameters",
  add_parameter: "parameters",
  modify_parameter: "parameters",
  // diagnostics
  fusion_status: "diagnostics",
  fusion_diagnostics: "diagnostics",
  // Bridge-owned helpers; never forwarded to the add-in.
  [HEALTH_TOOL]: "diagnostics",
  [CATEGORY_TOOL]: "diagnostics",
};

/** One category as list_tool_categories reports it. */
export interface CategoryListing {
  readonly name: ToolCategory;
  readonly description: string;
  readonly tools: string[];
}

/** What list_tool_categories returns. */
export interface ToolCategoriesReport {
  readonly categories: CategoryListing[];
  /** Live tools actually classified; equals the sum of the per-category lists. */
  readonly total_tools: number;
}

const CATEGORY_DESCRIPTIONS: Readonly<Record<ToolCategory, string>> = {
  viewport: "Seeing and steering the active viewport: capture, camera read, camera set.",
  selection: "Reading what the user currently has selected in the viewport.",
  documents: "Creating, opening, saving, exporting and closing Fusion documents.",
  parameters: "Reading and editing the user parameters that drive the model.",
  documentation: "Searching the Fusion API and reading the bundled design guide.",
  diagnostics: "Readiness, health and reliability of the bridge and the add-in.",
};

/**
 * The live classification. Derived from ALLOWED on every call, so a name that is
 * not live cannot appear even if it is classified above — and a PENDING or
 * BLOCKED_HARD name, never classified, is absent by construction.
 */
export function listToolCategories(): ToolCategoriesReport {
  const byCategory: Record<ToolCategory, string[]> = {
    viewport: [],
    selection: [],
    documents: [],
    parameters: [],
    documentation: [],
    diagnostics: [],
  };

  let total = 0;
  for (const name of ALLOWED) {
    const category = CATEGORY_BY_TOOL[name];
    if (category === undefined) continue; // unclassified: the drift guard fails the build
    byCategory[category].push(name);
    total++;
  }

  return {
    categories: TOOL_CATEGORIES.map((name) => ({
      name,
      description: CATEGORY_DESCRIPTIONS[name],
      tools: byCategory[name],
    })),
    total_tools: total,
  };
}

/**
 * The tools/list entry for the bridge-owned category listing. Advertised
 * alongside the proxied surface even when the add-in is unreachable.
 */
export function categoryTool(): Tool {
  return {
    name: CATEGORY_TOOL,
    description:
      "List the available tools grouped by category (viewport, selection, documents, parameters, " +
      "documentation, diagnostics), together with a short description of each group. Bridge-owned; " +
      "safe to call before any other tool to learn what this bridge can do. Only live tools appear; " +
      "roadmap tools are not listed.",
    inputSchema: { type: "object", properties: {} },
  };
}
