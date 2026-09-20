"""Real Fusion MCP smoke checks.

Run on a machine with Fusion 360 open and this add-in running::

    python -m pytest tests/smoke -m smoke -o addopts=''

The checks use the public MCP HTTP protocol only.  They intentionally do not
install the fake Fusion modules used by the unit-test suite.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytestmark = pytest.mark.smoke

_DEFAULT_URL = "http://127.0.0.1:8765/mcp"
_REPORT = Path(os.environ.get("FUSION_SMOKE_REPORT", "fusion-smoke-report.md"))
_PROTOCOL = "2026-07-28"


class SmokeClient:
    """Small MCP HTTP client for the add-in's public transport."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.host_port = urlparse(url).netloc
        self.request_id = 0

    def request(self, method: str, params: dict | None = None) -> dict:
        self.request_id += 1
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": method,
                "params": {**(params or {}), "_meta": {"io.modelcontextprotocol/protocolVersion": _PROTOCOL}},
            }
        ).encode()
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": _PROTOCOL,
                "Mcp-Method": method,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=float(os.environ.get("FUSION_SMOKE_TIMEOUT", "20"))) as response:
            raw = response.read().decode()
        if raw.startswith("data: "):
            raw = raw.split("data: ", 1)[1].splitlines()[0]
        return json.loads(raw)

    def call(self, name: str, **arguments: object) -> dict:
        response = self.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in response:
            raise RuntimeError(response["error"].get("message", "MCP error"))
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"Malformed MCP result for {name}")
        if result.get("isError"):
            raise RuntimeError(_result_text(result))
        return _result_data(result)


def _result_text(result: dict) -> str:
    content = result.get("content", [])
    return str(content[0].get("text", result)) if content else str(result)


def _result_data(result: dict) -> dict:
    text = _result_text(result)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}
    return value if isinstance(value, dict) else {"value": value}


def _record(config: pytest.Config, name: str, status: str, elapsed: float, reason: str = "") -> None:
    records = getattr(config, "_fusion_smoke_records", [])
    records.append((name, status, elapsed, reason))
    config._fusion_smoke_records = records


def _write_report(config: pytest.Config) -> None:
    markexpr = config.option.markexpr or ""
    if "smoke" not in markexpr or "not smoke" in markexpr:
        return
    records = getattr(config, "_fusion_smoke_records", [])
    endpoint = os.environ.get("FUSION_MCP_URL", _DEFAULT_URL)
    lines = [
        "# Fusion 360 MCP smoke report",
        "",
        f"Host/port: `{endpoint}`",
        "",
        "| Check | Status | Elapsed (s) | Details |",
        "|---|---|---:|---|",
    ]
    for name, status, elapsed, reason in records:
        lines.append(f"| {name} | {status} | {elapsed:.3f} | {reason.replace('|', '/')} |")
    _REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture(scope="session", autouse=True)
def smoke_report(request: pytest.FixtureRequest):
    """Collect rows and write the report only for an explicit smoke run."""
    request.config._fusion_smoke_records = []
    yield
    _write_report(request.config)


@pytest.fixture(scope="session")
def fusion_mcp(request: pytest.FixtureRequest) -> SmokeClient:
    url = os.environ.get("FUSION_MCP_URL", _DEFAULT_URL)
    client = SmokeClient(url)
    started = time.monotonic()
    try:
        client.request("tools/list")
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        _record(
            request.config,
            "MCP endpoint connection",
            "SKIP",
            time.monotonic() - started,
            f"Fusion/add-in unreachable: {exc}",
        )
        pytest.skip(f"Fusion MCP endpoint unreachable at {url}: {exc}")
    except Exception as exc:
        _record(request.config, "MCP endpoint connection", "FAIL", time.monotonic() - started, repr(exc))
        raise
    _record(request.config, "MCP endpoint connection", "PASS", time.monotonic() - started)
    return client


def _check(request: pytest.FixtureRequest, name: str, operation) -> dict:
    started = time.monotonic()
    try:
        result = operation()
    except RuntimeError as exc:
        message = str(exc)
        if _environment_unavailable(message):
            _record(request.config, name, "SKIP", time.monotonic() - started, message)
            pytest.skip(f"{name}: {message}")
        _record(request.config, name, "FAIL", time.monotonic() - started, repr(exc))
        raise
    except Exception as exc:
        _record(request.config, name, "FAIL", time.monotonic() - started, repr(exc))
        raise
    _record(request.config, name, "PASS", time.monotonic() - started)
    return result


def _environment_unavailable(message: str) -> bool:
    """Return whether a tool error names an explicitly unavailable fixture."""
    normalized = message.casefold()
    return any(
        phrase in normalized
        for phrase in (
            "fusion endpoint not reachable",
            "fusion/add-in unreachable",
            "fusion 360 is not reachable",
            "bridge stdio endpoint unavailable",
            "add-in not running",
            "fusion add-in not running",
            "missing live fusion fixture",
            "no live fusion fixture",
            "no active fusion document",
            "no active viewport",
        )
    )


def _bridge_stdio_call() -> dict:
    """Call the bridge-owned read-only health tool through its stdio transport."""
    repo_root = Path(__file__).resolve().parents[4]
    default_command = ["node", str(repo_root / "packages" / "bridge" / "dist" / "bin.js")]
    command = (
        shlex.split(os.environ["FUSION_BRIDGE_COMMAND"]) if os.environ.get("FUSION_BRIDGE_COMMAND") else default_command
    )
    request_data = (
        "\n".join(
            json.dumps(message)
            for message in (
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": _PROTOCOL,
                        "capabilities": {},
                        "clientInfo": {"name": "fusion-smoke", "version": "1.0"},
                    },
                },
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "fusion_health", "arguments": {}},
                },
            )
        )
        + "\n"
    )
    try:
        completed = subprocess.run(
            command,
            input=request_data,
            capture_output=True,
            text=True,
            timeout=float(os.environ.get("FUSION_SMOKE_TIMEOUT", "20")),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Fusion bridge stdio endpoint unavailable: {exc}") from exc
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    response = next((item for item in responses if item.get("id") == 2), None)
    if not isinstance(response, dict):
        detail = completed.stderr.strip() or "no response from bridge stdio endpoint"
        raise RuntimeError(f"Fusion bridge stdio endpoint unavailable: {detail}")
    if "error" in response:
        raise RuntimeError(str(response["error"].get("message", response["error"])))
    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Fusion bridge returned a malformed health response")
    if result.get("isError"):
        raise RuntimeError(_result_text(result))
    return result


def test_runtime_and_documents(fusion_mcp: SmokeClient, request: pytest.FixtureRequest) -> None:
    status = _check(request, "fusion_status", lambda: fusion_mcp.call("fusion_status"))
    assert isinstance(status, dict)
    documents = _check(request, "list_documents", lambda: fusion_mcp.call("list_documents"))
    assert isinstance(documents, dict)


def test_scratch_document_lifecycle_and_parameters(
    fusion_mcp: SmokeClient, request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    name = f"MCP smoke {os.getpid()}"
    created = _check(request, "new_document", lambda: fusion_mcp.call("new_document", name=name))
    assert isinstance(created, dict)
    save_path = tmp_path / "fusion-mcp-smoke.f3d"
    try:
        _check(request, "save_document", lambda: fusion_mcp.call("save_document", path=str(save_path)))
        _check(
            request,
            "export_document",
            lambda: fusion_mcp.call(
                "export_document", format="f3d", path=str(tmp_path / "fusion-mcp-smoke-export.f3d")
            ),
        )
        parameters = _check(request, "list_parameters", lambda: fusion_mcp.call("list_parameters"))
        assert isinstance(parameters, dict)
        parameter_name = f"mcp_smoke_{os.getpid()}"
        _check(
            request,
            "add_parameter",
            lambda: fusion_mcp.call("add_parameter", name=parameter_name, expression="10 mm", unit="mm"),
        )
        _check(
            request,
            "modify_parameter",
            lambda: fusion_mcp.call("modify_parameter", name=parameter_name, expression="12 mm"),
        )
    finally:
        with suppress(Exception):
            fusion_mcp.call("close_document", document_name=name, save=False)


def test_viewport_camera_and_selection(fusion_mcp: SmokeClient, request: pytest.FixtureRequest) -> None:
    camera = _check(request, "get_viewport", lambda: fusion_mcp.call("get_viewport"))
    assert isinstance(camera, dict)
    _check(request, "capture_viewport", lambda: fusion_mcp.call("capture_viewport", width=320, height=240))
    selection = _check(request, "get_active_selection", lambda: fusion_mcp.call("get_active_selection"))
    assert isinstance(selection, dict)


def test_documentation_lookup(fusion_mcp: SmokeClient, request: pytest.FixtureRequest) -> None:
    result = _check(
        request,
        "fetch_api_documentation",
        lambda: fusion_mcp.call("fetch_api_documentation", search_term="BRepBody", max_results=1),
    )
    assert isinstance(result, dict)


def test_wsl_bridge_read_only_leg(fusion_mcp: SmokeClient, request: pytest.FixtureRequest) -> None:
    """Exercise the local WSL-to-Windows leg without mutating Fusion state."""
    result = _check(request, "WSL bridge stdio fusion_health", _bridge_stdio_call)
    assert isinstance(result, dict)
