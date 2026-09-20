/**
 * JSON-Schema `examples` parity: can tool inputSchema properties carry an
 * `examples` keyword on both sides of the bridge/add-in contract?
 *
 * The answer hinges on how zod 4.6.x turns an examples intent into a keyword.
 * There is no `.examples()`/`.example()` builder in 4.6.5 — the only path is
 * `.meta({ examples: [...] })`, which `z.toJSONSchema` spreads verbatim as a
 * top-level keyword. These tests pin that emission contract so a zod upgrade
 * that changes it (or finally ships `.examples()`) fails loudly here rather
 * than silently breaking the cross-package drift guard.
 *
 * Scope of the verdict:
 *   - leaf properties (string/enum/boolean/array/number) — parity holds;
 *   - object-level and number-level examples — the drift guard rebuilds those
 *     branches by hand (see numberToJsonSchema / the ZodObject branch in
 *     drift-guard.test.ts) and would drop `examples` unless they learn to read
 *     it from z.globalRegistry.
 */

import { expect, it } from "vitest";
import { z } from "zod";

/** Mirrors the drift guard's normalize(): order-independent deep equality. */
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

/** What the drift guard keeps from z.toJSONSchema on a leaf ($schema stripped). */
function guardLeaf(schema: z.ZodType): Record<string, unknown> {
  const { $schema, ...rest } = z.toJSONSchema(schema) as Record<string, unknown>;
  return rest;
}

it("emits a byte-identical `examples` array for every leaf type", () => {
  const cases: Array<[string, z.ZodType, Record<string, unknown>]> = [
    ["string", z.string().meta({ examples: ["sketch1"] }), { type: "string", examples: ["sketch1"] }],
    ["string multi", z.string().meta({ examples: ["a", "b"] }), { type: "string", examples: ["a", "b"] }],
    [
      "enum",
      z.enum(["stl", "step"]).meta({ examples: ["stl"] }),
      { type: "string", enum: ["stl", "step"], examples: ["stl"] },
    ],
    ["boolean", z.boolean().meta({ examples: [true] }), { type: "boolean", examples: [true] }],
    ["number", z.number().meta({ examples: [5] }), { type: "number", examples: [5] }],
    ["nested object example", z.string().meta({ examples: [{ a: 1 }] }), { type: "string", examples: [{ a: 1 }] }],
  ];

  for (const [label, schema, expected] of cases) {
    const emitted = guardLeaf(schema);
    expect.soft(emitted, label).toStrictEqual(expected);
  }
});

it("survives the drift guard's leaf path, byte for byte", () => {
  // The guard compares normalize(zodSchema) against normalize(artifact) with
  // toStrictEqual. A leaf carrying examples must round-trip unchanged.
  const zodSide = guardLeaf(
    z
      .string()
      .describe("a desc")
      .meta({ examples: ["x"] }),
  );
  const addInSide = { type: "string", description: "a desc", examples: ["x"] };

  expect(normalize(zodSide)).toStrictEqual(normalize(addInSide));
});

it("does not matter whether .describe() or .meta() is applied first", () => {
  const describeFirst = z
    .string()
    .describe("a desc")
    .meta({ examples: ["x"] });
  const metaFirst = z
    .string()
    .meta({ examples: ["x"] })
    .describe("a desc");

  // Key order differs in emission, but normalize() sorts, so both compare equal
  // to the same hand-written schema — canonical comparison is order-insensitive.
  expect(normalize(guardLeaf(describeFirst))).toStrictEqual(normalize(guardLeaf(metaFirst)));
  expect(normalize(guardLeaf(describeFirst))).toStrictEqual(
    normalize({ type: "string", description: "a desc", examples: ["x"] }),
  );
});

it("leaves validation semantics untouched", () => {
  const schema = z.string().meta({ examples: ["x"] });
  expect(schema.safeParse("hello").success).toBe(true);
  expect(schema.safeParse(42).success).toBe(false);
});

it("keeps examples through optional/nullable wrappers", () => {
  expect(
    guardLeaf(
      z
        .string()
        .meta({ examples: ["x"] })
        .optional(),
    ),
  ).toStrictEqual({
    type: "string",
    examples: ["x"],
  });
});

it("is the only meta key that may be used: every other meta key leaks as a keyword", () => {
  // Discipline the contract relies on: meta is spread wholesale, so an
  // arbitrary key would become a schema keyword the add-in's whitelist rejects.
  const emitted = guardLeaf(z.string().meta({ examples: ["x"], internal: 1 }));
  expect(emitted).toStrictEqual({ type: "string", examples: ["x"], internal: 1 });
  expect(Object.keys(emitted)).toEqual(["type", "examples", "internal"]);
});

it("publishes examples through z.globalRegistry, not _zod.def.meta", () => {
  // The drift guard's hand-built number/object branches cannot read examples
  // from _zod.def; any extension of those branches must consult the registry.
  const withExamples = z.string().meta({ examples: ["x"] });
  expect(withExamples._zod.def.meta).toBeUndefined();
  expect(z.globalRegistry.get(withExamples)).toStrictEqual({ examples: ["x"] });
});

it("emits examples for numbers and objects via z.toJSONSchema, which the guard rebuilds by hand", () => {
  // Evidence for the gap: raw emission carries examples, but the guard's
  // numberToJsonSchema and ZodObject branches build the schema dict themselves
  // and currently drop it. Extending parity to numbers/objects means reading
  // z.globalRegistry.get(schema) in those two branches.
  expect(z.toJSONSchema(z.number().meta({ examples: [5] }))).toMatchObject({ examples: [5] });
  expect(z.toJSONSchema(z.object({ a: z.string() }).meta({ examples: [{ a: "x" }] }))).toMatchObject({
    examples: [{ a: "x" }],
  });
});
