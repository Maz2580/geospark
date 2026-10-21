"""Smoke test: the stdio MCP server starts and completes a real JSON-RPC handshake.

Runs the server as a subprocess, the way Claude Desktop launches ``geospark-mcp``,
so it catches breakage from MCP SDK upgrades that in-process mocks would miss.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

pytest.importorskip("mcp")

EXPECTED_TOOLS = {
    "check_spatial_relationship",
    "calculate_distance",
    "spatial_operation",
    "geocode",
    "reverse_geocode",
    "get_elevation",
}


def _rpc(msg_id: int | None, method: str, params: dict | None = None) -> str:
    msg: dict = {"jsonrpc": "2.0", "method": method}
    if msg_id is not None:
        msg["id"] = msg_id
    if params is not None:
        msg["params"] = params
    return json.dumps(msg) + "\n"


def test_stdio_server_handshake_lists_tools() -> None:
    stdin = (
        _rpc(
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test", "version": "0"},
            },
        )
        + _rpc(None, "notifications/initialized")
        + _rpc(2, "tools/list", {})
    )
    proc = subprocess.run(
        [sys.executable, "-m", "geospark.mcp_servers"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )
    responses = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            msg = json.loads(line)
            if "id" in msg:
                responses[msg["id"]] = msg

    assert 1 in responses, f"no initialize response; stderr:\n{proc.stderr[-2000:]}"
    assert responses[1]["result"]["serverInfo"]["name"] == "geospark"
    assert 2 in responses, f"no tools/list response; stderr:\n{proc.stderr[-2000:]}"
    names = {tool["name"] for tool in responses[2]["result"]["tools"]}
    assert names >= EXPECTED_TOOLS
