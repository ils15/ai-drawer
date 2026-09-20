# Real Fusion smoke tests

These tests require Autodesk Fusion 360 to be open with the add-in running.
They use the add-in's MCP HTTP endpoint and are skipped by the normal
`pyproject.toml` defaults.

On Windows/Fusion, from the add-in directory, run:

```powershell
py -m pytest tests/smoke -m smoke -o addopts=""
```

For a forwarded WSL endpoint, set `FUSION_MCP_URL` (default:
`http://127.0.0.1:8765/mcp`). The generated `fusion-smoke-report.md` contains
one row per check, status, elapsed time, and host/port.
