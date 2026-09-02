import { useState, type FormEvent } from "react";

import { ApiError, apiClient, type PublicRecordCheckInput, type PublicRecordCheckResult } from "../api";

function futureDate(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() + days);
  return value.toISOString().slice(0, 10);
}

function dollars(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(cents / 100);
}

function toCents(value: FormDataEntryValue | null): number {
  const amount = Number(value);
  return Number.isFinite(amount) ? Math.round(amount * 100) : 0;
}

export function LiveRecordCheck({ onBack }: { onBack: () => void }) {
  const [identifier, setIdentifier] = useState("");
  const [result, setResult] = useState<PublicRecordCheckResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload: PublicRecordCheckInput = {
      identifier_type: form.get("identifier_type") === "parcel" ? "parcel" : "permit",
      identifier: String(form.get("identifier") ?? "").trim(),
      claimed_year: Number(form.get("claimed_year")),
      closing_date: String(form.get("closing_date")),
      loan_amount_cents: toCents(form.get("loan_amount")),
      daily_delay_cost_cents: toCents(form.get("daily_delay_cost")),
      expected_delay_days: Number(form.get("expected_delay_days")),
      inspection_cost_cents: toCents(form.get("inspection_cost")),
    };
    setBusy(true);
    setError(null);
    try { setResult(await apiClient.checkPublicRecord(payload)); }
    catch (caught) { setError(caught instanceof ApiError ? caught.message : "The live record check could not be completed."); }
    finally { setBusy(false); }
  };

  return <main className="live-check-shell">
    <section className="live-check-intro">
      <button className="live-back" type="button" onClick={onBack}>← Back to modes</button>
      <p className="eyebrow"><i aria-hidden="true" /> LIVE DELAWARE PUBLIC DATA</p>
      <h2>Check a real permit record.</h2>
      <p>Every submission queries Delaware Open Data again. Enter a public permit or parcel identifier, then supply your own closing assumptions—the result is not a replay of the 47-loan demo.</p>
      <div className="live-truth-note"><strong>Privacy boundary</strong><span>Owner and address fields are never requested. No booking or external action occurs.</span></div>
    </section>

    <section className="live-check-workspace">
      <form className="live-check-form" onSubmit={(event) => void submit(event)}>
        <div className="form-section-heading"><span>01</span><div><strong>Official record</strong><small>Exact public identifier match</small></div></div>
        <label>Identifier type<select name="identifier_type" defaultValue="permit"><option value="permit">Permit number</option><option value="parcel">Parcel number</option></select></label>
        <label>Permit or parcel identifier<input name="identifier" value={identifier} onChange={(event) => setIdentifier(event.target.value)} placeholder="Enter an identifier or choose an example below" minLength={3} maxLength={64} pattern="[A-Za-z0-9. -]+" required /></label>
        <div className="public-examples"><span>Try a public example</span>{["0310-90S", "031177-90S", "031215-90S"].map((value) => <button type="button" key={value} onClick={() => setIdentifier(value)}>{value}</button>)}</div>
        <label>Claimed installation/replacement year<input name="claimed_year" type="number" defaultValue="2018" min="1900" max="2100" required /></label>

        <div className="form-section-heading"><span>02</span><div><strong>Your closing scenario</strong><small>Used only for disclosed planning math</small></div></div>
        <div className="form-grid">
          <label>Closing date<input name="closing_date" type="date" defaultValue={futureDate(10)} required /></label>
          <label>Loan amount ($)<input name="loan_amount" type="number" defaultValue="350000" min="10000" max="5000000" step="1000" required /></label>
          <label>Daily delay cost ($)<input name="daily_delay_cost" type="number" defaultValue="1250" min="0" max="100000" step="10" required /></label>
          <label>Expected delay (days)<input name="expected_delay_days" type="number" defaultValue="5" min="1" max="365" required /></label>
          <label>Inspection estimate ($)<input name="inspection_cost" type="number" defaultValue="480" min="0" max="100000" step="10" required /></label>
        </div>
        <button className="primary live-submit" disabled={busy}>{busy ? "Querying Delaware…" : "Run live record check"}</button>
        {error && <p className="live-error" role="alert">{error}</p>}
      </form>

      <div className="live-result" aria-live="polite">
        {result ? <Result result={result} /> : <div className="result-empty"><span>LIVE RESULT</span><strong>Waiting for an identifier</strong><p>The official record, date comparison, citation, and your scenario math will appear here.</p></div>}
      </div>
    </section>
  </main>;
}

function Result({ result }: { result: PublicRecordCheckResult }) {
  const record = result.record;
  const label = result.comparison === "aligned" ? "YEAR ALIGNED" : result.comparison === "needs_review" ? "REVIEW DIFFERENCE" : "NO EXACT MATCH";
  return <article className={`record-result ${result.comparison}`}>
    <header><span><i aria-hidden="true" /> FRESH QUERY COMPLETE</span><time>{new Date(result.retrieved_at).toLocaleString()}</time></header>
    <div className="result-verdict"><small>{label}</small><h3>{result.summary}</h3></div>
    <dl className="record-facts">
      <div><dt>County</dt><dd>{record?.county ?? "—"}</dd></div>
      <div><dt>Permit</dt><dd>{record?.permit_number ?? "No match"}</dd></div>
      <div><dt>Parcel reference</dt><dd>{record?.parcel_reference ?? "—"}</dd></div>
      <div><dt>Public record date</dt><dd>{record?.application_received_date ?? "—"}</dd></div>
      <div><dt>Status</dt><dd>{record?.permit_status ?? "—"}</dd></div>
      <div><dt>System type</dt><dd>{record?.system_type ?? "—"}</dd></div>
      <div><dt>Construction</dt><dd>{record?.construction_type ?? "—"}</dd></div>
      <div><dt>Claimed year</dt><dd>{result.claimed_year}</dd></div>
      <div><dt>Record year</dt><dd>{result.official_record_year ?? "—"}</dd></div>
      <div><dt>Closing</dt><dd>{result.closing_date} · {result.days_to_close} days</dd></div>
      <div><dt>Exact records</dt><dd>{result.matching_record_count}</dd></div>
    </dl>
    <div className="live-exposure">
      <span>USER-SUPPLIED SCENARIO</span>
      <div><p>Loan amount<strong>{dollars(result.exposure.loan_amount_cents)}</strong></p><p>Delay estimate<strong>{dollars(result.exposure.without_action_cents)}</strong></p><p>Inspection estimate<strong>{dollars(result.exposure.after_action_cents)}</strong></p><p>Potentially avoidable<strong>{dollars(result.exposure.preventable_cents)}</strong></p></div>
      <code>{result.exposure.formula}</code>
    </div>
    <footer>
      <p>{result.limitation}</p>
      <div>{record?.official_detail_url && <a href={record.official_detail_url} target="_blank" rel="noopener noreferrer">Open official DNREC record ↗</a>}<a href={result.dataset_url} target="_blank" rel="noopener noreferrer">Open source dataset ↗</a></div>
    </footer>
  </article>;
}
