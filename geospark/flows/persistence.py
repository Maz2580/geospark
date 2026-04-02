"""
Flow persistence — optional durable storage for flows and run history.

Provides a protocol-based abstraction so flows can be persisted to
Supabase or stay in-memory (default). The factory ``get_flow_store()``
reads ``GEOSPARK_FLOW_BACKEND`` from the environment.

Usage:
    store = get_flow_store()  # Returns SupabaseFlowStore or None
    if store:
        store.save_flow(flow)
        runs = store.list_runs(flow_id=flow.id)
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Protocol

from geospark.flows.flow_schema import Flow, FlowRun


class FlowPersistenceError(Exception):
    """Raised when a persistence operation fails."""


class FlowStore(Protocol):
    """Protocol for flow persistence backends."""

    def save_flow(self, flow: Flow) -> str: ...
    def get_flow(self, flow_id: str) -> Flow | None: ...
    def list_flows(self, limit: int = 100) -> list[Flow]: ...
    def delete_flow(self, flow_id: str) -> bool: ...
    def save_run(self, run: FlowRun) -> str: ...
    def get_run(self, run_id: str) -> FlowRun | None: ...
    def list_runs(self, flow_id: str | None = None, limit: int = 50) -> list[FlowRun]: ...


class SupabaseFlowStore:
    """Supabase-backed flow persistence.

    Stores flow definitions and run records as JSONB in Supabase tables.
    Requires ``SUPABASE_URL`` and ``SUPABASE_KEY`` environment variables.
    """

    def __init__(self, url: str | None = None, key: str | None = None) -> None:
        self._url = url or os.getenv("SUPABASE_URL", "")
        self._key = key or os.getenv("SUPABASE_KEY", "")
        if not self._url or not self._key:
            raise FlowPersistenceError(
                "SUPABASE_URL and SUPABASE_KEY required for Supabase flow store"
            )

        import httpx

        self._client = httpx.Client(
            base_url=f"{self._url}/rest/v1",
            headers={
                "apikey": self._key,
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            timeout=30,
        )

    def save_flow(self, flow: Flow) -> str:
        """Save or upsert a flow definition."""
        data = {
            "id": flow.id,
            "name": flow.name,
            "description": flow.description,
            "trigger_type": flow.trigger.trigger_type,
            "metadata": json.loads(json.dumps(flow.metadata, default=str)),
            "definition": json.loads(flow.model_dump_json()),
            "updated_at": datetime.utcnow().isoformat(),
        }
        resp = self._client.post(
            "/flows",
            content=json.dumps(data, default=str),
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        if resp.status_code not in (200, 201):
            raise FlowPersistenceError(f"Failed to save flow: {resp.text}")
        return flow.id

    def get_flow(self, flow_id: str) -> Flow | None:
        """Fetch a flow by ID."""
        resp = self._client.get(f"/flows?id=eq.{flow_id}&select=definition")
        if resp.status_code != 200:
            return None
        rows = resp.json()
        if not rows:
            return None
        return Flow(**rows[0]["definition"])

    def list_flows(self, limit: int = 100) -> list[Flow]:
        """List all saved flows."""
        resp = self._client.get(
            f"/flows?select=definition&order=updated_at.desc&limit={limit}"
        )
        if resp.status_code != 200:
            return []
        return [Flow(**row["definition"]) for row in resp.json()]

    def delete_flow(self, flow_id: str) -> bool:
        """Delete a flow and its runs (cascade)."""
        resp = self._client.delete(f"/flows?id=eq.{flow_id}")
        return resp.status_code in (200, 204)

    def save_run(self, run: FlowRun) -> str:
        """Save or update a flow run record."""
        data = {
            "id": run.id,
            "flow_id": run.flow_id,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "data": json.loads(run.model_dump_json()),
        }
        resp = self._client.post(
            "/flow_runs",
            content=json.dumps(data, default=str),
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        if resp.status_code not in (200, 201):
            raise FlowPersistenceError(f"Failed to save run: {resp.text}")
        return run.id

    def get_run(self, run_id: str) -> FlowRun | None:
        """Fetch a run by ID."""
        resp = self._client.get(f"/flow_runs?id=eq.{run_id}&select=data")
        if resp.status_code != 200:
            return None
        rows = resp.json()
        if not rows:
            return None
        return FlowRun(**rows[0]["data"])

    def list_runs(self, flow_id: str | None = None, limit: int = 50) -> list[FlowRun]:
        """List runs, optionally filtered by flow_id."""
        query = f"/flow_runs?select=data&order=started_at.desc&limit={limit}"
        if flow_id:
            query += f"&flow_id=eq.{flow_id}"
        resp = self._client.get(query)
        if resp.status_code != 200:
            return []
        return [FlowRun(**row["data"]) for row in resp.json()]


def get_flow_store() -> SupabaseFlowStore | None:
    """Factory: return a flow store based on environment config.

    Returns ``SupabaseFlowStore`` if ``GEOSPARK_FLOW_BACKEND=supabase``,
    otherwise ``None`` (in-memory mode, no persistence).
    """
    backend = os.getenv("GEOSPARK_FLOW_BACKEND", "").lower()
    if backend == "supabase":
        return SupabaseFlowStore()
    return None


def get_schema_sql() -> str:
    """Return SQL to create the flow persistence tables in Supabase."""
    return """
-- GeoSpark Flow Persistence Tables

CREATE TABLE IF NOT EXISTS flows (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    trigger_type TEXT NOT NULL DEFAULT 'manual',
    metadata JSONB DEFAULT '{}',
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_flows_name ON flows(name);

CREATE TABLE IF NOT EXISTS flow_runs (
    id UUID PRIMARY KEY,
    flow_id UUID NOT NULL REFERENCES flows(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_flow_runs_flow_id ON flow_runs(flow_id);
CREATE INDEX IF NOT EXISTS idx_flow_runs_status ON flow_runs(status);
"""
