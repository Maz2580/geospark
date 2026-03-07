# GeoSpark Flows — Spatial Workflow Designer

Design AI-powered spatial workflows that automate geospatial tasks. This skill helps you plan and architect GeoSpark Flows — the chat-to-workflow system inspired by n8n and Google Opal.

Use this when you need to design a spatial automation workflow, plan the Flows architecture, or prototype a workflow template.

## What Are GeoSpark Flows?

GeoSpark Flows let users describe a spatial task in natural language, and the AI builds an executable workflow. Think n8n, but:
- You **chat** to create the workflow instead of drag-and-drop
- Each step can have an **AI agent** that makes spatial decisions
- Agents can **message each other** within the workflow (Google Opal pattern)
- Workflows can be **triggered** by schedules, events, or data changes

## Flow Schema (Planned — Phase 3B)

A Flow is a DAG (directed acyclic graph) of steps. Each step is either:
- A **tool call** (geocode, satellite search, elevation query)
- An **AI decision** (agent evaluates conditions, picks next step)
- A **transform** (buffer, clip, merge, filter)
- A **human checkpoint** (pause and ask user for input)

```python
# Planned Pydantic models (from docs/ROADMAP.md)
class FlowStep(BaseModel):
    id: str
    type: Literal["tool", "agent", "transform", "human"]
    tool_name: str | None = None
    agent_prompt: str | None = None
    inputs: dict[str, str]         # Maps input names to step_id.output_name
    outputs: list[str]
    on_success: str | None = None  # Next step ID
    on_failure: str | None = None
    routes: list[FlowRoute] = []   # For dynamic routing

class FlowRoute(BaseModel):
    condition: str                  # Natural language or Python expression
    target_step: str               # Step ID to route to

class Flow(BaseModel):
    id: str
    name: str
    description: str
    steps: list[FlowStep]
    triggers: list[FlowTrigger] = []
    created_by: str
    version: str = "0.1.0"
```

## Design Process

When designing a workflow, follow this process:

### 1. Capture the User's Intent

Ask the user:
- What spatial task do they want to automate?
- What data sources are involved?
- How often should it run?
- What should happen when something fails?

### 2. Decompose into Steps

Break the task into atomic steps. Each step should do ONE thing:

```
Example: "Monitor deforestation in my region of interest"

Step 1: [tool]      Satellite search → find latest imagery for ROI
Step 2: [tool]      Satellite search → find imagery from 6 months ago
Step 3: [transform] Change detection → compare the two images
Step 4: [agent]     Evaluate → "Is the change significant (>5% area)?"
Step 5: [tool]      Geocode → identify the specific area of change
Step 6: [human]     Alert → notify user with map and summary
```

### 3. Design the Routing

Determine the flow control:
- **Linear**: Step 1 → Step 2 → Step 3 (most common)
- **Conditional**: If agent says "significant" → alert, else → log and exit
- **Parallel**: Run satellite search for multiple regions simultaneously
- **Loop**: Repeat weekly with new imagery

### 4. Define Agent Messages (Opal Pattern)

If the workflow has multiple AI agents, define what information they pass to each other:
- Agent A completes analysis → sends structured result to Agent B
- Agent B uses that context + its own tools to continue
- Each agent has a clear role and a system message defining its expertise

### 5. Output the Design

Create a visual diagram and a structured specification:

```
┌─────────┐     ┌───────────┐     ┌──────────┐
│ Satellite│────>│  Change   │────>│  Agent:  │
│  Search  │     │ Detection │     │ Evaluate │
└─────────┘     └───────────┘     └────┬─────┘
                                       │
                              ┌────────┴────────┐
                              │                 │
                        [significant]      [not significant]
                              │                 │
                        ┌─────v─────┐    ┌──────v──────┐
                        │  Alert    │    │   Log &     │
                        │  User     │    │   Archive   │
                        └───────────┘    └─────────────┘
```

## Workflow Templates (Planned)

These are pre-built flows that users can customize:

| Template | Steps | Use Case |
|----------|-------|----------|
| **Land Change Monitor** | satellite → change detection → alert | Environmental monitoring |
| **Site Suitability** | geocode → buffer → spatial query → rank | Real estate, infrastructure |
| **Disaster Response** | satellite → damage assessment → nearest facility → route | Emergency management |
| **Urban Growth Tracker** | satellite → classification → area calc → trend | City planning |
| **Supply Chain Risk** | geocode → proximity to hazards → risk score | Logistics |

## Current Status

GeoSpark Flows is **Phase 3B** in the roadmap. The foundation pieces that need to exist first:

- [x] Spatial reasoning engine (Phase 0 — done)
- [x] Tool registry and execution (Phase 0 — done)
- [x] MCP tool definitions (Phase 0 — done)
- [ ] Memory & session persistence (Phase 2D — needed for flow state)
- [ ] Plugin system (Phase 3D — needed for custom steps)
- [ ] Flow schema (Phase 3B — this is the core implementation)
- [ ] Flow executor (Phase 3B)
- [ ] Chat-to-flow builder (Phase 3B)
- [ ] Flow templates (Phase 3B)

## Key Design Decisions

These decisions shape the Flows architecture. Reference when implementing:

1. **Plan-then-act** (Google Opal): AI generates a complete plan before executing any step. User can review and modify before running.
2. **Dynamic routing**: Agents evaluate conditions at runtime and decide the next step. Not just static if/else — the agent reasons about the result.
3. **Persistent state**: Flow execution state is stored in Supabase so flows can be paused, resumed, and inspected.
4. **Agent messaging**: Agents within a flow can send structured messages to each other, carrying context forward without losing information.
5. **Idempotent steps**: Every step should be safely re-runnable. If a flow fails at step 4, it can resume from step 4 without re-running steps 1-3.

## How to Contribute to Flows

If you're working on Flows implementation:
1. Read `docs/ROADMAP.md` Phase 3B section for the full specification
2. The Flow schema goes in `geospark/flows/schema.py`
3. The executor goes in `geospark/flows/executor.py`
4. The chat-to-flow builder goes in `geospark/flows/builder.py`
5. Templates go in `geospark/flows/templates/`
6. Tests go in `tests/flows/`
