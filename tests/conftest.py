"""Test-wide isolation: no real network, no writes to the developer's home directory.

- Storage: ``GEOSPARK_DATA_DIR`` (and the audit/usage dirs) point at a temporary directory for
  the whole session, set before any GeoSpark module creates its stores.
- Network: connections to anything but localhost fail fast. Tests that really need the
  internet are marked ``@pytest.mark.network`` and run with ``pytest -m network``.
"""

from __future__ import annotations

import os
import socket
import tempfile

import pytest

_DATA_DIR = tempfile.mkdtemp(prefix="geospark-tests-")
os.environ["GEOSPARK_DATA_DIR"] = _DATA_DIR
os.environ["GEOSPARK_AUDIT_DIR"] = os.path.join(_DATA_DIR, "audit")
os.environ["GEOSPARK_USAGE_DIR"] = os.path.join(_DATA_DIR, "usage")

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}
_real_connect = socket.socket.connect


def _guarded_connect(self: socket.socket, address) -> None:  # type: ignore[no-untyped-def]
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, str) and host not in _LOCAL_HOSTS and not host.startswith("/"):
        raise OSError(
            f"Network access blocked in tests (tried {address}). "
            "Mock the call, or mark the test with @pytest.mark.network."
        )
    return _real_connect(self, address)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "network: test needs real internet access (run with -m network)")


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("network") is None:
        monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
