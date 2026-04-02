# GeoSpark Implementation Plan

## Implementation Status

- [x] `geospark/flows/persistence.py` — FlowStore protocol, SupabaseFlowStore, factory, schema SQL
- [x] `geospark/flows/flow_runner.py` — accepts optional store, persists run at each step
- [x] REST API: GET/POST/DELETE /api/v1/flows, POST /flows/{id}/run, GET /api/v1/flow-runs
- [x] 503 behavior when persistence not configured
- [x] DELETE endpoint (added per review feedback)
- [x] `data` JSONB column for flow_runs with step_results + errors (per review feedback)
- [x] CLI: `geospark flow saved/get/delete/runs` commands
- [x] get_schema_sql() for Supabase table creation
- [x] 446 tests passing, 0 lint errors
- [ ] Supabase tables created on live server (pending: run SQL in Supabase dashboard)
- [ ] GEOSPARK_FLOW_BACKEND=supabase added to VM .env (pending: enable after table creation)
- [ ] Integration tests with mock Supabase (future)

## Scope

Primary objective: add flow persistence to Supabase without breaking zero-config local usage.

In scope:
- Persist `Flow` definitions
- Persist `FlowRun` records and status transitions
- Add an optional persistence abstraction so local installs can stay in-memory
- Add REST endpoints for saved flows and run history
- Add `DELETE` support for saved flows
- Add tests for store behavior, runner integration, and API behavior

Out of scope:
- Visual flow editor
- Scheduling engine
- Chat-to-flow generation
- Interactive per-step chat
- Broad database abstraction beyond the immediate flow store need
- `PUT`/update for saved flows in the first pass

## Current State

Existing flow pieces:
- `geospark/flows/flow_schema.py`: `Flow`, `FlowStep`, `FlowRoute`, `FlowRun`, `FlowTrigger`
- `geospark/flows/flow_runner.py`: in-memory execution only
- `geospark/flows/templates.py`: template registry and builders
- `geospark/api.py`: template listing and template execution endpoints only
- `geospark/integrations/supabase_db.py`: existing Supabase integration and schema SQL generator

Current gap:
- Flows are executable but not durable
- No persisted flow definitions
- No persisted run history
- No API for saved flows or run retrieval

## Proposed Architecture

Add a new module:
- `geospark/flows/persistence.py`

Objects:
- `FlowStore`: protocol/interface for persistence backends
- `SupabaseFlowStore`: concrete Supabase implementation
- `get_flow_store()`: environment-driven factory
- `FlowPersistenceError`: backend/configuration failure type

Import surface:
- Re-export `get_flow_store()` and related persistence objects from `geospark/flows/__init__.py` so the import path stays clean for `api.py` and any later callers.

Why this shape:
- Keeps `FlowRunner` decoupled from Supabase details
- Preserves current in-memory default behavior
- Makes later backends possible without reshaping flow execution
- Lets API and runner share the same persistence surface

## Schema Changes

Prefer additive SQL changes in `geospark/integrations/supabase_db.py`.

### New table: `flows`
- `id UUID PRIMARY KEY`
- `name TEXT NOT NULL`
- `description TEXT DEFAULT ''`
- `trigger_type TEXT NOT NULL DEFAULT 'manual'`
- `metadata JSONB DEFAULT '{}'`
- `definition JSONB NOT NULL`
- `created_at TIMESTAMPTZ DEFAULT NOW()`
- `updated_at TIMESTAMPTZ DEFAULT NOW()`

Indexes:
- `idx_flows_name ON flows(name)`
- `idx_flows_trigger_type ON flows(trigger_type)`

### New table: `flow_runs`
- `id UUID PRIMARY KEY`
- `flow_id UUID NOT NULL REFERENCES flows(id) ON DELETE CASCADE`
- `status TEXT NOT NULL`
- `started_at TIMESTAMPTZ`
- `completed_at TIMESTAMPTZ`
- `data JSONB NOT NULL`
- `created_at TIMESTAMPTZ DEFAULT NOW()`

Indexes:
- `idx_flow_runs_flow_id ON flow_runs(flow_id)`
- `idx_flow_runs_status ON flow_runs(status)`
- `idx_flow_runs_started_at ON flow_runs(started_at DESC)`

### Storage strategy
Store the full serialized `FlowRun.model_dump()` payload in `flow_runs.data`.

Why:
- `step_results` and `errors` are core run-history fields and should not be implicitly buried or partially duplicated
- `data` is a clearer name than `definition` for execution records
- top-level searchable columns remain available for filtering and listing

For `flows`, keep `definition JSONB` because it is a saved definition rather than an execution record.

## Model Changes

Keep model changes minimal.

Required model changes:
- None, if persistence is implemented externally via JSONB serialization

Optional future model improvements:
- Add `updated_at` to `Flow`
- Add explicit `version` in `Flow.metadata`

For this implementation, avoid widening model scope unless a concrete persistence need appears.

## Runner Changes

Update `geospark/flows/flow_runner.py`:
- Accept optional `store: FlowStore | None`
- Persist `FlowRun` at run start
- Persist after each successful step
- Persist on failure
- Persist on successful completion

Behavior:
- If `store` is `None`, current behavior remains unchanged
- If a store is configured, runner writes durable run state transitions

## API Changes

Keep existing template endpoints unchanged.

### New endpoints

Flow definitions:
- `GET /api/v1/flows`
  - List persisted flows
- `POST /api/v1/flows`
  - Save a flow definition
- `GET /api/v1/flows/{flow_id}`
  - Get a saved flow definition
- `DELETE /api/v1/flows/{flow_id}`
  - Delete a saved flow definition
- `POST /api/v1/flows/{flow_id}/run`
  - Run a saved flow definition

Flow runs:
- `GET /api/v1/flow-runs`
  - List run records, optionally filtered by `flow_id`
- `GET /api/v1/flow-runs/{run_id}`
  - Get a specific run record

### API behavior rules
- If persistence is not configured, persistence-only endpoints should return `503`
- Template endpoints should keep working without persistence
- Running a saved flow should use `FlowRunner(engine=get_engine(), store=store)`
- Deleting a flow should cascade-delete run history at the database level via the `flow_runs.flow_id` foreign key

### Configuration
Add environment variable:
- `GEOSPARK_FLOW_BACKEND`

Supported values:
- empty or `memory`: disable persistence
- `supabase`: enable Supabase-backed flow storage

## CLI Changes

Recommendation: keep CLI changes out of the first pass.

Reason:
- API-first is enough to validate the persistence layer
- Avoid over-expanding the initial implementation

## Testing Plan

### Unit tests: `tests/test_flows.py`
Add tests for:
- `SupabaseFlowStore.save_flow()` / `get_flow()` / `list_flows()` / `delete_flow()`
- `SupabaseFlowStore.save_run()` / `get_run()` / `list_runs()`
- `FlowRunner` persistence integration with a fake store
- `get_flow_store()` factory behavior from environment variables

Testing approach:
- Use fake/mock Supabase client objects
- Do not depend on live network access
- Keep persistence tests deterministic and isolated

### API tests: `tests/test_api.py`
Add tests for:
- listing saved flows
- saving a flow
- fetching a saved flow
- deleting a saved flow
- running a saved flow
- fetching a saved run
- `503` behavior when persistence is disabled

Testing approach:
- monkeypatch the flow store factory in the API layer
- avoid real Supabase access

### Regression checks
Ensure unchanged behavior for:
- existing template flow endpoints
- non-flow endpoints
- local in-memory usage without persistence config

### Verification commands after implementation
- `.venv/Scripts/python.exe -m pytest tests/ -x -q --tb=short`
- `.venv/Scripts/python.exe -m ruff check geospark/ tests/`

## Deployment Plan

Local:
- no persistence unless `GEOSPARK_FLOW_BACKEND=supabase`

Supabase:
- extend `get_schema_sql()` with additive SQL only
- no destructive migration required

VM rollout:
- keep persistence staged behind configuration
- do not add `GEOSPARK_FLOW_BACKEND=supabase` to the VM until implementation is tested locally and reviewed
- after verification, enable the env var and apply the additive SQL schema
- do not affect UrbanMind containers or port 80

## Deployment Verification Item

Separate from the persistence implementation, verify the live API version drift.

Observed issue:
- the live API currently reports `0.1.0` in `/health` and OpenAPI metadata while the package version is `0.3.0`

Action:
- check `https://geospark.terrascout.app/health`
- if the API still reports `0.1.0` after the persistence work is merged, rebuild/redeploy the container and verify the live version matches the codebase

This is a deployment/versioning issue, not part of the persistence feature itself, but it should be tracked and cleaned up.

## Risks

Primary risks:
- Supabase response handling may require careful normalization
- JSONB storage is flexible but less queryable than fully normalized tables
- Flow persistence endpoints add API surface and need clear disabled-state behavior
- Delete behavior must remain safe and predictable, especially with cascading run deletion

## Review Decisions Captured

Confirmed decisions from review:
1. API-only in the first pass
2. Add `DELETE` immediately, defer `UPDATE`
3. Stage persistence behind config and do not enable on VM until verified
4. Keep vertical datum work separate from this implementation

## Separate Follow-Up: Vertical Datum Feedback

Do Phase A only for now.

### Immediate response
- Update documentation to state known elevation assumptions explicitly
- Say when vertical datum is unknown
- Warn that mixed sources or undocumented vertical systems can differ by tens of meters

### Deferred work
Defer the following until there is stronger product pressure for it:
- elevation metadata wrapper fields
- source-aware datum inference helper
- vertical datum inference tests beyond documentation-linked checks

### Rationale
The feedback is geospatially valid, but most current GeoSpark use cases are not blocked by it. A docs-first response captures the correctness concern without delaying the higher-priority roadmap item.
