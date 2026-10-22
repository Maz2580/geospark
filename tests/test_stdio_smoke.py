"""Smoke test: the stdio MCP server starts and completes a real JSON-RPC handshake.

Runs the server as a subprocess, the way Claude Desktop launches ``geospark-mcp``,
so it catches breakage from MCP SDK upgrades that in-process mocks would miss.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

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


def _send(proc: subprocess.Popen, msg: dict) -> None:
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", **msg}) + "\n")
    proc.stdin.flush()


def _reply(proc: subprocess.Popen, msg_id: int, timeout_s: float = 60) -> dict:
    """Read stdout until the response with ``msg_id`` arrives."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break  # server exited
        if line.startswith("{"):
            msg = json.loads(line)
            if msg.get("id") == msg_id:
                return msg
    raise AssertionError(f"no response to request {msg_id}; stderr:\n{proc.stderr.read()[-2000:]}")


def test_stdio_server_handshake_lists_tools() -> None:
    # Wait for each reply before sending the next message, like a real MCP client.
    # Closing stdin early makes the server exit before it answers (seen on slow CI runners).
    proc = subprocess.Popen(
        [sys.executable, "-m", "geospark.mcp_servers"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _send(proc, {
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test", "version": "0"},
            },
        })
        init = _reply(proc, 1)
        assert init["result"]["serverInfo"]["name"] == "geospark"

        _send(proc, {"method": "notifications/initialized"})
        _send(proc, {"id": 2, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in _reply(proc, 2)["result"]["tools"]}
        assert names >= EXPECTED_TOOLS
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
