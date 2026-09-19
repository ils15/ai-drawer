# NOTICE

## Attribution

`fusion360-mcp` is a **derivative work** of **`autodesk-fusion-mcp`**, created
and copyright by **Frank Hommers** (https://github.com/frankhommers).

- Upstream project : https://github.com/frankhommers/autodesk-fusion-mcp
- Upstream license  : MIT (see below)
- Upstream version at the time of the fork : **v1.4.1**
  (commit `ff5f43afb8cc150ba59f54f2d0e91d1187e67683`)

The upstream source was incorporated into this monorepo under
`packages/addin/` using `git subtree add`, which **preserves the full upstream
commit history** as ancestors of this repository's history. Upstream commits
therefore retain their original authorship and are not relicensed or
re-attributed. Every commit made directly by this project is authored by the
`fusion360-mcp` contributors.

## What changed relative to upstream

This project keeps the upstream **infrastructure** (Streamable HTTP transport,
main-thread dispatch queue, viewport capture, test bootstrap) and **replaces
the upstream tool surface**:

- Removed `execute_python` (arbitrary Python execution / RCE vector).
- Removed `call_autodesk_api` (generic dotted-path API caller).
- Removed the user-script store (`save_script`, `load_script`, `list_scripts`,
  `delete_script`).
- Added `MCP_SERVER_HOST` to `settings.py` so the HTTP server bind address is
  configurable (defaults to loopback, `127.0.0.1`).

A curated, capability-oriented CAD tool surface is added in a later wave.

## Upstream MIT license

```
MIT License

Copyright (c) 2026 Frank Hommers

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
