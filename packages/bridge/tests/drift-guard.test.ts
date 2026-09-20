/**
 * Cross-package drift guard: the bridge's TypeScript view vs the add-in's
 * Python surface.
 *
 * The contract artifact (tests/contract/addin-tool-surface.json) is GENERATED
 * from the live packages/addin/fusion_bridge/tool_surface.py by
 * tests/contract/generate.mjs. This test pins the bridge to that artifact, so
 * the two packages can never drift apart silently:
 *
 *   1. no phantoms  — every ALLOWED name is a real add-in tool (or the
 *      bridge-owned health probe);
 *   2. no orphans   — every add-in tool is classified exactly once, in ALLOWED,
 *      PENDING or BLOCKED_HARD;
 *   3. coverage     — every forwarded tool has a zod entry in TOOL_ARGS;
 *   4. parity       — each zod entry, introspected, equals the artifact schema
 *      (type/properties/required/enum/bounds/additionalProperties) and carries
 *      the artifact's descriptions byte for byte.
 *
 * The mutation tests below prove the guard can actually fail: a guard that
 * cannot fail is decoration.
 */

import { expect, it } from "vitest";
import { z } from "zod";
import { ALLOWED, BLOCKED_HARD, HEALTH_TOOL, PENDING } from "../src/allowlist.js";
// server.ts keeps TOOL_ARGS module-private; re-exported here so the guard can
// introspect the live schemas the bridge actually validates with.
import { TOOL_ARGS } from "../src/server.js";
import artifact from "./contract/addin-tool-surface.json";

interface ArtifactTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

/** Properties zod emits for a leaf; everything else is rebuilt by hand. */
type Emitted = { $schema?: string } & Record<string, unknown>;

/** Peeks at zod internals that have no public accessor in 4.6.x. */
interface ZodInternals {
  _zod: {
    def: {
      catchall?: unknown;
      innerType?: z.ZodType;
    };
  };
}

function unwrap(schema: z.ZodType): z.ZodType {
  let current: z.ZodType = schema;
  while (current instanceof z.ZodOptional || current instanceof z.ZodNullable) {
    current = (current as unknown as ZodInternals)._zod.def.innerType as z.ZodType;
  }
  return current;
}

/** True when the object rejects unknown keys (z.object().strict()). */
function isStrict(schema: z.ZodType): boolean {
  const internals = schema as unknown as ZodInternals;
  return schema instanceof z.ZodObject && internals._zod.def.catchall instanceof z.ZodNever;
}

/**
 * Converts a zod schema to the JSON Schema shape the artifact speaks. Objects
 * are rebuilt by hand (zod's own emitter reports additionalProperties:false for
 * plain z.object() too, which is not what the add-in declares); leaves reuse
 * zod's emitter, which is authoritative for type/enum/minimum/maximum.
 */
function toJsonSchema(schema: z.ZodType): Record<string, unknown> {
  const core = unwrap(schema);
  const description: string | undefined = schema.description ?? core.description;

  if (core instanceof z.ZodObject) {
    const properties: Record<string, Record<string, unknown>> = {};
    const required: string[] = [];
    for (const [key, value] of Object.entries(core.shape)) {
      properties[key] = toJsonSchema(value as z.ZodType);
      if (!(value as z.ZodType).isOptional()) required.push(key);
    }
    const out: Record<string, unknown> = { type: "object", properties };
    if (required.length > 0) out.required = required;
    if (isStrict(core)) out.additionalProperties = false;
    if (description !== undefined) out.description = description;
    return out;
  }

  if (core instanceof z.ZodNumber) return numberToJsonSchema(core, description);

  const emitted = z.toJSONSchema(core) as Emitted;
  const { $schema, ...rest } = emitted;
  if (description !== undefined && rest.description === undefined) rest.description = description;
  return rest;
}

/**
 * Reads a zod number the way the add-in would describe it. zod's own emitter
 * derives ±Number.MAX_SAFE_INTEGER bounds from the safeint check behind
 * .integer(); the add-in declares no such bounds, so only bounds set explicitly
 * (via .min()/.max()) are reported, alongside the integer-ness itself.
 */
function numberToJsonSchema(schema: z.ZodType, description: string | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = { type: "number" };
  const checks = (schema as unknown as { _zod: { def: { checks?: Array<CheckLike> } } })._zod.def.checks ?? [];
  for (const check of checks) {
    const merged: CheckLike = { ...check.def, ...check._zod?.def };
    if (merged.check === "number_format" && merged.format === "safeint") out.type = "integer";
    if (merged.check === "greater_than" && merged.inclusive !== false && typeof merged.value === "number") {
      out.minimum = merged.value;
    }
    if (merged.check === "less_than" && merged.inclusive !== false && typeof merged.value === "number") {
      out.maximum = merged.value;
    }
  }
  if (description !== undefined) out.description = description;
  return out;
}

interface CheckLike {
  def?: Record<string, unknown>;
  _zod?: { def?: Record<string, unknown> };
  check?: string;
  format?: string;
  inclusive?: boolean;
  value?: unknown;
}

/** Where an add-in tool name sits. `orphan` means classified nowhere. */
function classify(name: string): "allowed" | "pending" | "blocked" | "orphan" {
  if (ALLOWED.has(name)) return "allowed";
  if (PENDING.includes(name)) return "pending";
  if (BLOCKED_HARD.has(name)) return "blocked";
  return "orphan";
}

/**
 * Runs every guard assertion. Collects all violations before throwing, so a
 * single failure surfaces everything wrong at once.
 */
function assertSurfaceInSync(): void {
  const tools = (artifact as { tools: ArtifactTool[] }).tools;
  const byName = new Map(tools.map((tool) => [tool.name, tool]));
  const violations: string[] = [];

  const forwarded = [...ALLOWED].filter((name) => name !== HEALTH_TOOL);

  // 1. No phantoms: every forwarded name is a tool the add-in really serves.
  for (const name of forwarded) {
    if (!byName.has(name)) violations.push(`ALLOWED lists '${name}', but the add-in does not serve it`);
  }

  // The health probe is bridge-owned: allowed, and deliberately absent upstream.
  if (!ALLOWED.has(HEALTH_TOOL)) violations.push(`bridge-owned ${HEALTH_TOOL} must stay in ALLOWED`);
  if (byName.has(HEALTH_TOOL))
    violations.push(`${HEALTH_TOOL} is bridge-owned; it must not appear in the add-in artifact`);

  // 2. No orphans: every add-in tool is classified exactly once. The three
  //    buckets must be pairwise disjoint (no name may sit in two of them).
  const buckets: Array<[string, Set<string>]> = [
    ["ALLOWED", new Set(ALLOWED)],
    ["PENDING", new Set(PENDING)],
    ["BLOCKED_HARD", new Set(BLOCKED_HARD)],
  ];
  for (let i = 0; i < buckets.length; i++) {
    for (let j = i + 1; j < buckets.length; j++) {
      for (const name of buckets[i][1]) {
        if (buckets[j][1].has(name)) {
          violations.push(`'${name}' is classified in both ${buckets[i][0]} and ${buckets[j][0]}`);
        }
      }
    }
  }
  for (const tool of tools) {
    const kind = classify(tool.name);
    if (kind === "orphan") {
      violations.push(`add-in tool '${tool.name}' is an orphan: not in ALLOWED, PENDING or BLOCKED_HARD`);
    }
  }

  // 3. Coverage: every forwarded tool has a zod entry.
  for (const name of forwarded) {
    if (!(name in TOOL_ARGS)) violations.push(`ALLOWED tool '${name}' has no TOOL_ARGS entry`);
  }
  // No TOOL_ARGS entry may exist for a name the gate does not admit.
  for (const name of Object.keys(TOOL_ARGS)) {
    if (!ALLOWED.has(name)) violations.push(`TOOL_ARGS has an entry for '${name}', which is not in ALLOWED`);
  }

  // 4. Parity: schema and descriptions match the artifact byte for byte.
  for (const name of forwarded) {
    const tool = byName.get(name);
    const schema = TOOL_ARGS[name];
    if (tool === undefined || schema === undefined) continue;

    // The artifact's tool description lives beside inputSchema; the zod entry
    // carries it as the root .describe().
    if (schema.description !== tool.description) {
      violations.push(`description drift on '${name}':\n  zod: ${schema.description}\n  add-in: ${tool.description}`);
    }

    // Compare inputSchema with the root description stripped (it is not part of
    // the add-in's inputSchema) and keys order-independent.
    const { description: _drop, ...zodSchema } = toJsonSchema(schema);
    if (!isEqual(normalize(zodSchema), normalize(tool.inputSchema))) {
      violations.push(
        `schema drift on '${name}':\n  zod: ${JSON.stringify(zodSchema)}\n  add-in: ${JSON.stringify(tool.inputSchema)}`,
      );
    }
  }

  if (violations.length > 0) {
    throw new Error(`bridge/add-in surface is out of sync:\n${violations.map((v) => `  - ${v}`).join("\n")}`);
  }
}

/** Order-independent, undefined-tolerant deep equality (mirrors toEqual). */
function normalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalize);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .map(([key, child]) => [key, normalize(child)])
        .sort(([a], [b]) => a.localeCompare(b)),
    );
  }
  return value;
}

function isEqual(a: unknown, b: unknown): boolean {
  try {
    expect(a).toStrictEqual(b);
    return true;
  } catch {
    return false;
  }
}

it("keeps the bridge in sync with the add-in contract artifact", () => {
  expect(artifact.tools).toHaveLength(18);
  assertSurfaceInSync();
});

it("reports the expected tool count through the live allowlist", () => {
  // 18 add-in tools + the bridge-owned health probe.
  expect([...ALLOWED]).toHaveLength(19);
});

/* ── Mutation proof: the guard must fail when the surface drifts ─────────── */

const mutableAllowed = ALLOWED as unknown as Set<string>;
const mutableArgs = TOOL_ARGS as Record<string, z.ZodType>;

it("fails when ALLOWED admits a tool the add-in does not serve", () => {
  mutableAllowed.add("definitely_not_an_addin_tool");
  try {
    expect(() => assertSurfaceInSync()).toThrow("does not serve it");
  } finally {
    mutableAllowed.delete("definitely_not_an_addin_tool");
  }
});

it("fails when a live add-in tool is dropped from ALLOWED (becomes an orphan)", () => {
  mutableAllowed.delete("fusion_status");
  try {
    expect(() => assertSurfaceInSync()).toThrow("is an orphan");
  } finally {
    mutableAllowed.add("fusion_status");
  }
});

it("fails when a forwarded tool loses its TOOL_ARGS entry", () => {
  const original = mutableArgs.export_document;
  delete mutableArgs.export_document;
  try {
    expect(() => assertSurfaceInSync()).toThrow("has no TOOL_ARGS entry");
  } finally {
    mutableArgs.export_document = original;
  }
});

it("fails when a zod schema no longer matches the add-in schema", () => {
  const original = mutableArgs.new_document;
  mutableArgs.new_document = z.object({ bogus_property: z.string() });
  try {
    expect(() => assertSurfaceInSync()).toThrow("schema drift on 'new_document'");
  } finally {
    mutableArgs.new_document = original;
  }
});

it("fails when a description string drifts from the add-in's wording", () => {
  const original = mutableArgs.list_documents;
  mutableArgs.list_documents = z.object({}).strict().describe("a paraphrase the add-in would not recognize");
  try {
    expect(() => assertSurfaceInSync()).toThrow("description drift on 'list_documents'");
  } finally {
    mutableArgs.list_documents = original;
  }
});
