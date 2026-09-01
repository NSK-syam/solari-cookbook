# Closing Rescue on Solari

Closing Rescue is a cinematic, local-first operations product that scans a deterministic 47-loan mortgage portfolio and finds the one septic-permit contradiction most likely to delay closing. It calculates the avoidable exposure, proposes a synthetic inspection slot, and stops at a durable one-time human approval before any GUI action.

This is a real use of all three Solari products:

- **Sandbox:** sends all 47 loans and their raw formula inputs to an isolated microVM. The guest independently checks every exposure calculation, preserves `contradiction` versus `no_match`, and returns a hash-addressed manifest with the input hash, flagged cases, formula version, and exit status.
- **Browser:** discovers a current permit through the [Delaware Open Data API](https://data.delaware.gov/Energy-and-Environment/Permitted-Septic-Systems/mv7j-tx3u), follows the returned official DNREC detail URL in a recorded Solari browser, redacts owner rows in the DOM, and captures a screenshot, citation, session ID, and replay.
- **Desktop:** remains locked until the existing approval token is consumed. It then opens a non-submittable local inspection-request form in a Solari desktop, fills an approval note with GUI input, and captures a screenshot receipt. It never books or pays for anything.

## Run locally

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 22+, and one Solari API key.

```bash
cp .env.example .env
# add SOLARI_API_KEY=slr_live_... to .env
make install
make start
```

Open [http://localhost:5173](http://localhost:5173), select **Start the rescue**, and use **Run live Solari proof** in the right rail. `make start` is the single command that launches FastAPI and the Vite app; both processes are cleaned up together on exit.

Fixture mode is deterministic and contains no lender, borrower, vendor-customer, or real loan data. Without `SOLARI_API_KEY`, the complete product and test suite still run, while the explicit live-proof endpoint returns `503` instead of pretending a cloud run occurred.

## Reviewer walkthrough

1. Start the 47-loan investigation and watch the six persisted chapters.
2. Open the evidence ledger to verify truth labels, citations, and timestamps.
3. Run the Solari proof. Inspect the sandbox manifest and browser replay/screenshot in the execution rail.
4. Skip to the finding. Confirm the $18,000 / $4,800 / $13,200 formulas are disclosed.
5. Approve the simulated rescue. The desktop unlocks only after the one-time approval, fills the non-submittable form, and adds its receipt to the rail.

## Architecture

```mermaid
flowchart LR
    UI["Cinematic React investigation"] --> API["Existing FastAPI /api/v2 workflow"]
    API --> DB["SQLite approvals, story, Solari receipts"]
    API --> S["Solari sandbox\n47-loan verification"]
    API --> B["Solari browser\nrecorded official permit"]
    API --> G{"Human approval consumed?"}
    G -->|No| L["Desktop locked"]
    G -->|Yes| D["Solari desktop\nsimulated form receipt"]
    S --> R["Visible execution rail"]
    B --> R
    D --> R
```

The Solari orchestration depends on three small adapter protocols. Ordinary CI uses deterministic fakes; the live implementations use the official Python SDKs (`solari-browser==0.1.2`, `solari-sandbox==0.2.0`, `solari-desktop==0.2.0`). Each billable resource has its own timeout and `finally` cleanup. One product failure is persisted as a partial failure and does not erase the other receipts.

## Verification

```bash
make test          # 402 backend tests + 62 frontend tests
make lint          # Ruff + TypeScript
make build         # production Vite bundle
make smoke-solari  # one real run of all three products; requires SOLARI_API_KEY
```

Tests cover deterministic ranking, contradiction/no-match distinctions, formulas, approval recovery, token enforcement, redaction, timeouts, partial failures, idempotency, and exact-once fake-resource cleanup. The live smoke command fails clearly when no key is configured and prints only redacted public receipts when it succeeds.

## Data and safety

- Owner names returned by Delaware Open Data are excluded from the discovery projection and hidden before browser screenshots.
- API keys, cookies, browser endpoints, and owner fields are rejected from persisted receipt text.
- Only hash-named JSON/image artifacts are served; paths are constrained to the configured artifact directory.
- The desktop form is local, visibly labeled simulation-only, and has a disabled submit button.
- Browser, sandbox, and desktop sessions are independently closed and killed/released.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/PRIVACY.md](docs/PRIVACY.md), and [docs/LIMITATIONS.md](docs/LIMITATIONS.md) for deeper boundaries. Deployment, the 60–90 second demo recording, and LinkedIn/X publication are deliberately deferred until a real-key walkthrough passes.
