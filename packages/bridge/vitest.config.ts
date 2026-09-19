import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    exclude: ["node_modules", "dist"],
    // These tests bind real ephemeral ports and hit the filesystem; a longer
    // budget keeps them deterministic on a loaded CI machine.
    testTimeout: 10_000,
    hookTimeout: 10_000,
    // Connection tests measure idle windows; a predictable pool avoids noise.
    pool: "forks",
  },
  // Connection tests measure idle windows; a predictable pool avoids noise.
  poolOptions: { forks: { singleFork: true } },
});
