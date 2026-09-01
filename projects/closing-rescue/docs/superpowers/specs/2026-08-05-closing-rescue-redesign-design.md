# Closing Rescue Redesign

Date: 2026-08-05
Status: Approved for implementation planning

## Product decision

Rename the platform **Closing Rescue** and present **Septic Sentinel** as its first specialist agent. The submission remains focused on septic due diligence, but the platform framing makes the buyer and expansion path clear: a regional mortgage lender can deploy additional specialist agents for other physical-world closing risks later.

The redesign must stop behaving like a case dashboard. It will become a guided agent investigation that begins with a lender's portfolio, autonomously selects the most preventable closing risk, gathers cited evidence, identifies a contradiction, calculates exposure, finds a viable intervention, requests human approval, acts in simulation, and re-evaluates the outcome.

## Buyer and problem

The initial buyer is the head of mortgage operations or closing operations at a regional lender. This buyer loses staff time and money when property-condition questions appear shortly before closing. A septic record gap can trigger manual searches, rate-lock extensions, rescheduling, and rushed inspections.

The product's commercial claim is intentionally narrow: Closing Rescue helps an operations team identify and pursue preventable property due-diligence delays earlier. It does not approve credit, diagnose septic failure, certify property condition, accuse a seller of misrepresentation, or guarantee savings.

## Demonstration thesis

The winning moment is not a dashboard metric. It is the agent finding something material that a human workflow missed and acting soon enough to protect a closing.

The judged fixture demonstration uses 47 synthetic active loans totaling $14.2 million. The agent chooses a $412,000 loan at 91 Marsh Road because it closes in six days and has the highest preventable exposure. It then discovers that a synthetic seller disclosure claims a 2018 septic replacement while the latest cited Delaware permit record is from 1991. Mireye physical evidence and recent NOAA precipitation increase inspection urgency without diagnosing failure. The agent finds one viable simulated inspection appointment, asks a human to approve it, records the simulated booking, and recalculates projected exposure from $18,000 to $4,800, protecting an estimated $13,200.

## Experience sequence

The primary experience is a guided investigation lasting no more than 75 seconds from start to completed simulated rescue.

1. **Portfolio scan — 0 to 8 seconds.** Show 47 loans, $14.2 million in pipeline value, four attention candidates, and the total estimated exposure. The agent visibly scores the portfolio and selects the highest-value preventable intervention. The user does not choose the case.
2. **Case selection — 8 to 15 seconds.** Introduce 91 Marsh Road, its $412,000 loan amount, six-day closing window, and the reason it outranks the other cases. Provide an expandable scoring explanation.
3. **Evidence investigation — 15 to 35 seconds.** Reveal persisted evidence events sequentially: Mireye property resolution and physical-world evidence, the synthetic seller disclosure, Delaware permit results, NOAA precipitation, and simulated vendor availability. Every external factual result shows its source, timestamp, and status.
4. **Contradiction — 35 to 47 seconds.** Place the seller claim and permit record side by side. Label the result as a record contradiction requiring resolution. Do not infer fraud, unpermitted work, or system failure.
5. **Rescue calculation — 47 to 60 seconds.** Show estimated exposure without intervention and projected residual exposure after the proposed inspection. Make each input and formula inspectable. Clearly label the result as a planning estimate rather than guaranteed savings.
6. **Human checkpoint and action — 60 to 75 seconds.** Present the only viable simulated inspection window, price, vendor, and rationale. Require a one-time approval. After approval, record the simulated booking, update the audit trail, and show the revised case state.

The experience must include pause, resume, replay, skip-to-result, and reduced-motion behavior. Skipping animation changes presentation only; it must not bypass persisted events, evidence validation, or approval controls.

## Visual system

The interface combines three complementary visual languages instead of applying one dashboard theme everywhere.

- **Documentary pacing** controls the guided investigation. Each chapter presents one sentence, one decision, or one reveal at a time. Progress is shown as six chapters rather than a generic loading bar.
- **Spatial forensics** appears during the Mireye chapter. The resolved property and physical evidence become the visual stage. Maps or terrain visuals are evidence context, not the primary navigation.
- **Editorial authority** presents the contradiction, explanation, and final memo using restrained typography and report-like hierarchy.

Avoid neon interfaces, generic dark analytics panels, dense card grids, decorative AI activity, and unexplained risk gauges. Motion must correspond to a persisted agent event. The application remains understandable when animation is disabled.

## Data truth boundaries

The judged experience combines live-capable cited sources with clearly marked synthetic business data.

### Live-capable and cited

- Mireye property resolution, terrain, flood, and related physical-world facts
- Delaware septic permit records
- NOAA recent precipitation observations

Fixture mode uses frozen normalized responses from those adapter contracts so the judged sequence is reliable. Live contract tests independently verify current compatibility.

### Synthetic and visibly labeled

- Lender loan tape and portfolio values
- Seller disclosure
- Rate-lock and operational cost assumptions
- Inspector directory, pricing, and appointment availability
- Vendor booking result

Synthetic values must never be presented as third-party live data. UI labels, evidence metadata, and documentation must all preserve this distinction.

## Domain additions

### Portfolio loan

A portfolio loan contains an external loan identifier, property address, loan amount, closing date, rate-lock daily cost, estimated rescheduling cost, seller claims, approved vendor constraints, and fixture scenario. It excludes borrower identity, credit data, protected-class data, and underwriting outcome.

### Priority assessment

A priority assessment stores urgency, contradiction severity, evidence completeness, intervention availability, preventable exposure, the component scores, the formula version, and a human-readable selection explanation. The score is deterministic and snapshot-based.

### Claim and contradiction

A claim is a normalized statement from a source, including whether the source is synthetic or external. A contradiction links two or more claims, identifies the incompatible fields and dates, records confidence, and specifies the evidence needed to resolve it. Missing records alone do not form a contradiction.

### Vendor option

A vendor option stores synthetic provider name, appointment time, price, service type, approval-list status, and availability timestamp. Only approved vendors with an appointment before the operational cutoff may be proposed.

### Exposure estimate

An exposure estimate stores all monetary inputs, the deterministic formula, estimated exposure without action, estimated exposure after action, preventable exposure, and limitations. The demonstration uses a $24,000 delay consequence assembled from a $12,600 rate-lock extension, $9,000 rescheduling cost, and $2,400 staff handling cost. Without action, the 75% planning probability produces `$24,000 × 0.75 = $18,000` estimated exposure. After the proposed $480 inspection, an 18% residual planning probability produces `($24,000 × 0.18) + $480 = $4,800`. Preventable exposure is `$18,000 - $4,800 = $13,200`.

No language model may generate or modify these monetary inputs or calculations.

## System components

### Portfolio intake

Loads the deterministic 47-loan competition fixture and supports future CSV ingestion behind the same interface. It validates required values and rejects borrower or credit fields rather than storing them.

### Priority engine

Scores every eligible loan using versioned deterministic rules. Missing evidence and source failures can only maintain or increase uncertainty; they cannot improve a loan's risk assessment. The engine returns the selected case and the next alternatives so judges can inspect why the agent chose it.

### Evidence adapters

The existing Mireye, Delaware, NOAA, and fixture adapters remain isolated. They continue returning normalized evidence with success, not-found, ambiguous, or unavailable status and preserved citations.

### Disclosure adapter

Converts the synthetic seller disclosure into normalized claims. Disclosure text is untrusted data and cannot modify agent policy or instructions.

### Contradiction engine

Compares normalized claims through deterministic field, date, and identifier rules. It distinguishes direct contradiction, missing corroboration, and source unavailability. Each finding links back to the claims and citations that produced it.

### Vendor scout

Searches synthetic vendor fixtures for approved, qualified appointments before the case cutoff. It records considered options and explains why alternatives were rejected. It cannot book an appointment.

### Exposure engine

Calculates the before-action and after-action planning estimates. The UI exposes the inputs and formula. The engine uses versioned calculations and rejects incomplete or negative cost inputs.

### Rescue planner

Combines the selected case, evidence ledger, contradictions, vendor options, and exposure estimates into a structured proposed rescue. It may use a language model for concise explanation, but all facts, monetary values, permissions, and citations come from validated stored data.

### Approval and action controller

Reuses the existing one-time token, approver identity, idempotency, and timeout-reconciliation controls. The only competition action is a simulated inspection booking. Approval creates an immutable audit event before execution.

### Story controller

Maps persisted domain events into the six visual chapters. It controls presentation timing, pause, replay, and skip behavior without fabricating events. Refreshing the page reconstructs the correct chapter from backend state.

## Data flow

1. Portfolio intake persists the synthetic loan tape.
2. The priority engine computes and stores assessments for all eligible loans.
3. The orchestrator selects the highest preventable-exposure case and records the selection event.
4. Evidence sources run concurrently after property resolution; each result is persisted before presentation.
5. The contradiction engine evaluates normalized claims.
6. The vendor scout finds viable synthetic options.
7. The exposure engine computes transparent before-and-after estimates.
8. The rescue planner creates the proposed intervention and cited explanation.
9. The story controller reveals the persisted results in chapter order.
10. A valid human approval triggers the simulated booking.
11. The priority and exposure engines re-evaluate the case and portfolio.

## Failure behavior

- Ambiguous property resolution stops external joins and requests clarification.
- A Mireye, Delaware, or NOAA failure is displayed as unavailable evidence and increases uncertainty.
- A completed record search with no match remains distinct from a failed search.
- Conflicting parcel identifiers stop the rescue and route to manual review.
- Missing cost inputs suppress the savings comparison rather than substituting invented values.
- No qualifying vendor option produces a county-record or manual-escalation recommendation instead of a fake appointment.
- Invalid reasoner output retries once, then falls back to deterministic copy and manual review.
- An unknown simulated booking result enters reconciliation and cannot be retried until resolved.
- Reloading, replaying, or skipping the story cannot duplicate source calls, approvals, or actions.

## API changes

Add versioned endpoints for portfolio fixture creation, portfolio summary, ranked priority assessments, selected investigation retrieval, story-event polling, exposure detail, and rescue approval. Existing case, evidence, citation, memo, and approval endpoints remain compatible where practical.

The primary frontend read model should return the portfolio summary, selected case, chapter state, evidence events, contradictions, exposure estimate, proposed rescue, approval state, and source truth labels in one response. This avoids assembling contradictory visual state from multiple client-side requests.

## Testing strategy

Automated coverage must include:

- deterministic ranking and stable tie-breaking across all 47 fixture loans
- selection of the intended six-day closing case
- direct contradiction versus missing corroboration
- exposure formulas, rounding, invalid inputs, and formula-version persistence
- source truth labels and citation integrity
- source failure and ambiguous property behavior
- prompt-like text in seller disclosures
- vendor qualification, cutoff, ordering, and no-availability behavior
- one-time approval, replay resistance, and action reconciliation
- persisted event order and page-refresh reconstruction
- pause, replay, skip, and reduced-motion presentation
- responsive desktop and mobile layouts
- the full 75-second journey and an accelerated automated equivalent

The deterministic test suite must not require network access. Separately marked live contract tests will verify Mireye, Delaware, and NOAA compatibility.

## Release acceptance

The redesign is ready only when:

- the agent autonomously selects the intended priority from 47 loans
- the reason for selection and every scoring component is inspectable
- the seller-permit contradiction is accurately labeled and source-linked
- every factual external claim has a stored citation and timestamp
- every synthetic datum is visibly labeled in the UI and API
- before-and-after exposure exactly matches the documented deterministic formula
- the approval cannot be bypassed or replayed
- the simulated booking changes the persisted case and portfolio state
- the guided sequence completes in 75 seconds or less and the accelerated test completes reliably
- the application has zero browser console errors at desktop and mobile widths
- reduced-motion mode preserves the complete information hierarchy
- a clean clone installs, tests, builds, and starts from documented commands
- a backup recording of the tagged build is available

## Explicit exclusions

- Real lender credentials, borrower data, credit decisions, or underwriting automation
- Real vendor outreach, payment, or appointment booking
- Nationwide permit normalization
- Septic condition diagnosis or licensed inspection claims
- Machine-learned delay probabilities
- Unsupported guaranteed-savings language
- Multiple specialist agents beyond Septic Sentinel in this submission

## Submission message

“Closing Rescue watches the lender's pipeline and deploys specialist agents before physical-world problems derail a closing. Septic Sentinel selected this loan from 47 active files, combined Mireye's cited property intelligence with permit and weather evidence, caught a 27-year record contradiction, found the only inspection window that could protect Friday's closing, and asked a human before acting. Every fact is sourced. Every estimate shows its work.”
