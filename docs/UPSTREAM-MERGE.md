# Upstream sync — `packages/addin`

The add-in at `packages/addin` is a **git subtree** of
[`frankhommers/autodesk-fusion-mcp`](https://github.com/frankhommers/autodesk-fusion-mcp)
(the `upstream` remote). This document is the authoritative procedure for
pulling upstream changes into it, and the record of what we have deliberately
diverged from upstream.

Read this before running any `git merge` or `git subtree` command against
`upstream`.

---

## 1. The only correct merge path: `git subtree pull`

```bash
git subtree pull --prefix=packages/addin upstream/main
```

That is the **only** supported way to bring upstream work in. `git subtree`
records the subtree's own commit history (commit `f914cac`, *"Add
'packages/addin/' from commit 'ff5f43a'"*) and uses that shared history to
compute a real merge, so every upstream file lands at
`packages/addin/<same relative path>` and conflicts are reported in terms of
the paths we actually edit.

Do **not** substitute `git merge upstream/main`, `git rebase`, or a manual
`git read-tree`. See §2 for why a plain merge is actively harmful here.

## 2. Verified pitfall: `git merge upstream/main` silently drops files at the repo root

**Confirmed finding** (validated in a throwaway sandbox during Wave 1, not
theoretical):

A plain `git merge upstream/main` does **not** move upstream's files into
`packages/addin`. Upstream's tree has the add-in at the repository root
(`lib/mcp_server.py`, `fusion_bridge/operations.py`, `settings.py`, …), while
our tree has the same files one level down under `packages/addin/`. Git has no
path information to work with, so it falls back to **rename detection**:

- Files it manages to pair up (`lib/mcp_server.py` →
  `packages/addin/lib/mcp_server.py`) merge as rename/modify conflicts — noisy,
  but at least visible.
- **Files with no detected rename are written at the repo root instead of under
  `packages/addin`.** New upstream files are the dangerous case: they appear as
  untracked-at-root additions, so an upstream addition silently lands in the
  wrong place and is easily missed, or is later deleted as "stray root files" —
  losing upstream work.

The failure mode is silent. `git status` looks like a successful merge that
left a few extra files at the root. There is no error and no warning naming the
real problem, which is why it is worth treating `git merge upstream/main` as
forbidden rather than merely discouraged.

`git subtree pull` avoids the entire class of problem because it merges within
the recorded prefix.

## 3. Exact upstream-sync procedure

Copy-pasteable. Run from the **repository root** (`/home/ils15/mcp/fusion360`),
on a clean working tree.

```bash
# 0. Prerequisite: nothing uncommitted, on main.
git status --porcelain && git checkout main

# 1. Refresh the upstream remote.
git fetch upstream

# 2. See what is coming, in subtree terms, BEFORE merging.
git log --oneline HEAD..upstream/main

# 3. Merge upstream into the subtree (this is the merge command — see §1).
git subtree pull --prefix=packages/addin upstream/main

# 4. If it reports conflicts, resolve them (conflict zones in §4), then:
git add -A
git commit
#    (git subtree leaves a MERGE_MSG; keep or edit it, but keep the
#     "Add 'packages/addin/' from commit ..." style subject so the
#     subtree link stays greppable.)

# 5. Verify the RCE strip survived the merge.
cd packages/addin
grep -rnE "execute_python|call_autodesk_api|save_script|load_script|list_scripts|delete_script" \
    --include='*.py' . | grep -v '/tests/'
#    ^ must print nothing. tests/ is allowed to name the banned tools.

# 6. Verify the tool surface and the suite.
python3 -c "from fusion_bridge import tool_surface; \
print(sorted(t['name'] for t in tool_surface.TOOL_DEFINITIONS))"
python3 -m ruff check .
python3 -m pytest
```

Step 5 is not paranoia: a subtree pull can resurrect the stripped modules and
tool definitions, and `tests/test_removed_tools.py` exists to fail loudly in
exactly that case. If it fails, resolve by keeping **our** deletions (see §4).

## 4. Known conflict zones

These files are intentionally **not byte-identical to upstream**. They will
conflict on (almost) every merge that touches them. The resolution is to keep
our side unless the upstream change is a genuine bug fix, in which case port
the fix by hand onto our version.

### `lib/mcp_server.py` — host configurability + removed legacy tool surface

Our changes vs upstream:

- New `host: str = "127.0.0.1"` constructor parameter and `self.host`, used as
  the bind address in `ThreadingHTTPServer((self.host, self.port), …)` and in
  the startup log lines. Upstream hardcodes `"127.0.0.1"`. This is required so
  the bind interface is configurable (WSL → Windows-host networking needs a
  different address) without editing library code — see `settings.py`.
- Legacy single-tool defaults: `tool_name` default is `"call_tool"` (upstream:
  `"call_autodesk_api"`), and the legacy single-tool `inputSchema` no longer
  documents the removed `operation`/`api_path`/`code`/`session_id`/… fields.
- Removed the session-id validation guard (see `lib/mcp_http_2026.py` below).
- Modern typing (`dict`/`X | None` instead of `typing.Dict`/`Optional`,
  `collections.abc.Callable`) plus `from __future__ import annotations`, applied
  to satisfy the `UP` ruff rules without requiring Python 3.10+ at runtime.

**Resolution policy:** keep the `host` parameter and the bind/log changes;
re-apply any upstream server fixes onto our version. The typing
modernization is cosmetic — if upstream churns these lines, prefer our
version and re-run `python3 -m ruff check .`.

### `lib/mcp_http_2026.py` — removed session-id guard

We deleted the block in the modern-protocol tool-call path that validated a
`session_id` for persistent `execute_python` / `call_autodesk_api` calls (10
lines, in `_handle_tool_call`). It exists only to guard tools we no longer
serve, and leaving it would keep a reference to removed capability in a
request-handling path.

**Resolution policy:** if upstream modifies that block, keep our deletion.

### `fusion_bridge/python_exec.py` and `fusion_bridge/script_store.py` — always conflict

These exist in upstream (at the equivalent subtree paths) and are **deleted on
our side**. Every subtree pull that touches them reports a
modify/delete-style conflict, expected to resolve in ~3 lines: accept the
deletion (`git rm`), and additionally confirm the tools are absent from the
registry (step 5 above) plus `tests/test_removed_tools.py`.

### Files made lint-clean

Wave 1 also applied `ruff` (rules `E,F,I,UP,B,SIM`, configured in
`packages/addin/pyproject.toml`) across the subtree. Import ordering and typing
modernization touch many files, so expect small textual conflicts on
import blocks. These are low-risk: resolve them by keeping our sorted imports
and re-running `python3 -m ruff check .` from `packages/addin`.

Vendored upstream copies in `lib/fusionAddInUtils/` and `third_party/` are
**excluded** from ruff (see `pyproject.toml`) and must stay byte-identical to
upstream; never fix lint findings in them by hand — that would diverge the
subtree for no benefit.

## 5. The 3 inherited tests that were modified (and why "all tests unmodified" was unsatisfiable)

The suite was inherited from upstream and is run unmodified wherever possible.
Three test files had to change as a direct consequence of removing the
high-risk tool surface. These are the minimal changes; every other test file is
untouched.

1. **`tests/test_tool_contract.py`** — hardcoded the expected 13-tool set.
   Removed the six banned tool names (`execute_python`, `call_autodesk_api`,
   `save_script`, `load_script`, `list_scripts`, `delete_script`) from the
   expected set, and deleted `test_call_autodesk_api_has_api_path` and
   `test_execute_python_has_code_field`, which asserted the *presence* of
   removed tools and therefore cannot pass against the stripped surface.
2. **`tests/test_http_protocols.py`** — `test_explicit_python_state_for_modern_only`
   exercised the deleted `session_id` guard in the modern protocol path. With
   the guard (and the tools it protected) gone, the test had nothing to assert.
3. **`tests/test_server_lifecycle.py`** — one line: `runtime.python_exec` →
   `runtime.version_info`, because the version-reporting helper was extracted
   out of the deleted `python_exec` module into `fusion_bridge/version_info.py`.

The removal is independently guarded by **`tests/test_removed_tools.py`**,
which fails if a future merge reintroduces any banned tool or module — that
file is ours, not inherited.

---

## 6. What is inherited and what is ours

The inherited surface is the **7 upstream tools** that were kept as-is:

`capture_viewport`, `get_viewport`, `set_viewport`, `fetch_api_documentation`,
`fetch_online_documentation`, `fetch_design_guide`, `get_active_selection`
(upstream itself ships 13; the other 6 were the removed RCE tools, §4).

Everything beyond those 7 is ours, written against the Fusion API directly:

| Group | Tools | Count |
| --- | --- | --- |
| documents | `new_document`, `open_document`, `save_document`, `export_document`, `close_document`, `list_documents`, `get_document_info` | 7 |
| parameters | `add_parameter`, `list_parameters`, `modify_parameter` | 3 |
| diagnostics | `fusion_status`, `fusion_diagnostics` | 2 |
| features | `create_sketch`, `extrude`, `revolve`, `create_component`, `create_body`, `apply_appearance`, `fillet`, `chamfer`, `hole`, `rectangular_pattern`, `circular_pattern` | 11 |
| inspection | `list_bodies`, `inspect_entity`, `list_features`, `measure` | 4 |

That is 27 tools of ours on top of the 7 inherited, for **34** served by the
add-in. The bridge (`packages/bridge`, outside this subtree entirely) adds two
it answers itself — `fusion_health` and `list_tool_categories` — for 36 total.

Consequence for merges: upstream releases touch the inherited 7 and the shared
modules in §4. Our five groups live in files upstream does not have
(`fusion_bridge/tools/*.py`), so they conflict only with their own history —
but the registry in `fusion_bridge/tool_surface.py` and the counts in
`tests/test_tool_contract.py` must be re-read after every merge, because an
upstream tool rename or addition changes the totals those tests pin.

---

## Quick reference

| Question | Answer |
|---|---|
| Merge command | `git subtree pull --prefix=packages/addin upstream/main` |
| Forbidden | `git merge upstream/main` (silently drops files at repo root, §2) |
| Run tests from | `packages/addin` — `python3 -m pytest` (the suite uses pytest markers; `unittest discover` cannot import `tests/`) |
| Lint from | `packages/addin` — `python3 -m ruff check .` |
| Coverage of changed modules | `python3 -m coverage run --include='*/fusion_bridge/tool_surface.py,*/fusion_bridge/operations.py,*/fusion_bridge/version_info.py,*/lib/mcp_server.py,*/lib/mcp_http_2026.py,*/settings.py' -m pytest && python3 -m coverage report -m` |
| Banned-tool guard | `tests/test_removed_tools.py` |
| Inherited surface | `capture_viewport`, `get_viewport`, `set_viewport`, `fetch_api_documentation`, `fetch_online_documentation`, `fetch_design_guide`, `get_active_selection` (7; upstream ships 13) |
| Tools served today | 34 add-in tools across 8 categories (7 inherited + 27 ours, see §6), plus 2 bridge-owned (`fusion_health`, `list_tool_categories`) |
