# Architecture

## System view

```mermaid
flowchart LR
    L["47-loan synthetic portfolio"] --> API["FastAPI /api/v2 workflow"]
    API --> O["Evidence orchestrator"]
    O --> M["Mireye MCP"]
    O --> D["Delaware Socrata"]
    O --> N["NOAA / NWS"]
    M --> E["Normalized evidence ledger"]
    D --> E
    N --> E
    E --> P["Deterministic policy gates"]
    P --> R["Structured reasoning"]
    R --> S{"Disposition"}
    S -->|Clear| Memo["Cited memo"]
    S -->|Investigate| A["Approval card"]
    S -->|Inspect| A
    A --> X["Simulated external action"]
    X --> E
    API --> SB["Solari sandbox manifest"]
    API --> BR["Recorded Solari browser"]
    A --> DS["Approval-gated Solari desktop"]
    SB --> UI["Execution receipt rail"]
    BR --> UI
    DS --> UI
```

## Deep boundaries

- `adapters/` hides each external protocol and converts responses into the same evidence envelope.
- `orchestrator.py` resolves the property first, then collects independent sources concurrently.
- `policy.py` owns non-negotiable safety gates. The language model cannot bypass them.
- `reasoner.py` separates cited observations from inferences and produces a typed decision.
- `actions.py` owns one-time approvals, idempotency, and simulated delivery.
- `repository.py` owns SQLite persistence, immutable decision snapshots, and append-only audit events.
- `solari_execution.py` owns the three typed product adapters, per-resource cleanup, timeouts, redacted artifacts, and partial-failure semantics.
- `api.py` exposes a versioned contract and never logs request bodies.

## Case sequence

```mermaid
sequenceDiagram
    participant User as Lender reviewer
    participant Agent as Septic Sentinel
    participant Sources as Mireye + public sources
    participant Store as Evidence ledger

    User->>Agent: Submit property case
    Agent->>Sources: Resolve and collect in parallel
    Sources-->>Agent: Values, provenance, timestamps
    Agent->>Store: Persist evidence snapshot
    Agent->>Agent: Apply policy gates and reason
    Agent-->>User: Cited disposition and proposed action
    User->>Agent: Approve or reject
    Agent->>Store: Record simulated action and audit event
```

## Trust model

External content is untrusted data. The model receives normalized payloads with owner and geometry fields removed, cannot invent evidence, and cannot authorize actions. Ambiguous locations, missing required evidence, and material source failures block clearance.
