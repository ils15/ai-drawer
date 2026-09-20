/**
 * Regenerates addin-tool-surface.json — the committed contract artifact.
 *
 * The artifact is the single source of truth for the cross-package drift guard
 * (tests/drift-guard.test.ts). It is GENERATED, never hand-edited: this script
 * imports the live add-in tool_surface.py and dumps its TOOL_DEFINITIONS, so
 * the bridge's TypeScript view can never silently drift from the Python surface
 * the add-in actually serves.
 *
 * Usage:  node tests/contract/generate.mjs
 *
 * Requires python3 on PATH. tool_surface.py is a pure-data module (no adsk
 * import), so it imports cleanly outside Fusion.
 */

import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

// tests/contract -> tests -> bridge -> packages -> repo root
const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..", "..", "..");
const addinPkg = resolve(repoRoot, "packages", "addin", "fusion_bridge");
const artifact = resolve(here, "addin-tool-surface.json");

// Extract the tool surface from the live Python source. Importing the module
// resolves every constant (DESIGN_TYPES, STL_UNITS, POINT_SCHEMA, ...) and
// comprehension, so the dump is exactly what the add-in advertises.
const script = `
import json, sys
sys.path.insert(0, ${JSON.stringify(addinPkg)})
import tool_surface

defs = []
for t in tool_surface.TOOL_DEFINITIONS:
    defs.append({
        "name": t["name"],
        "description": t["description"],
        "inputSchema": t["inputSchema"],
    })
json.dump({"generated_from": "packages/addin/fusion_bridge/tool_surface.py",
           "tools": defs}, sys.stdout, indent=2, sort_keys=False)
sys.stdout.write("\\n")
`;

const result = spawnSync("python3", ["-c", script], { encoding: "utf8", maxBuffer: 1 << 26 });
if (result.error !== undefined) {
  throw new Error(`failed to run python3: ${result.error.message}`);
}
if (result.status !== 0) {
  throw new Error(`python3 exited ${result.status}: ${result.stderr}`);
}

/** Verifies the generated blob before it is committed. */
function validate(text) {
  const parsed = JSON.parse(text);
  const names = parsed.tools.map((tool) => tool.name);
  if (names.length !== 18) throw new Error(`expected 18 add-in tools, got ${names.length}`);
  const dupes = names.filter((name, index) => names.indexOf(name) !== index);
  if (dupes.length > 0) throw new Error(`duplicate tool names in artifact: ${dupes.join(", ")}`);
}

const text = result.stdout;
validate(text);
writeFileSync(artifact, text);
console.log(`wrote ${artifact} (${JSON.parse(text).tools.length} tools)`);
