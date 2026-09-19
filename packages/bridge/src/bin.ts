#!/usr/bin/env node
/**
 * ai-drawer-mcp — stdio entrypoint.
 *
 * OpenCode spawns this via `npx -y ai-drawer-mcp`. It boots the MCP server on
 * stdio and proxies allowed tools to the AutodeskFusionMCP add-in inside
 * Fusion over Streamable HTTP.
 *
 * The process exits when the client closes stdin. A Fusion that is closed, or
 * whose add-in has not been started, is NOT fatal: the bridge stays up and
 * every tools/call returns the actionable tier-(c) guidance.
 */

import { runStdio } from "./server.js";

async function main(): Promise<void> {
  let exiting = false;

  const shutdown = (signal: string): void => {
    if (exiting) return;
    exiting = true;
    console.error(`[ai-drawer-mcp] received ${signal}, shutting down`);
  };

  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));

  try {
    await runStdio();
  } catch (error) {
    // Never write JSON to stdout: that channel is the MCP transport.
    console.error(`[ai-drawer-mcp] fatal: ${formatError(error)}`);
    process.exitCode = 1;
  }
}

function formatError(error: unknown): string {
  if (error instanceof Error) return error.stack ?? `${error.name}: ${error.message}`;
  return String(error);
}

await main();
