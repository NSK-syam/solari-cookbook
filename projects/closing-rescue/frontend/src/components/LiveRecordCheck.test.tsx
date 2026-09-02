import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveRecordCheck } from "./LiveRecordCheck";

const result = {
  query_type: "permit",
  query_value: "0310-90S",
  comparison: "needs_review",
  summary: "The submitted year differs from the public record's application-received year; verify the underlying documents.",
  claimed_year: 2018,
  official_record_year: 1990,
  closing_date: "2026-09-10",
  days_to_close: 9,
  matching_record_count: 1,
  record: { permit_number: "0310-90S", parcel_reference: "1-34-07.00-0430.00", application_received_date: "1990-06-28", permit_status: "Completion Report Received", system_type: "Gravity", construction_type: "New Construction", county: "Sussex", official_detail_url: "https://den.dnrec.delaware.gov/Detail/PermitDetail.aspx?id=60484984" },
  exposure: { loan_amount_cents: 35_000_000, daily_delay_cost_cents: 125_000, expected_delay_days: 5, inspection_cost_cents: 48_000, without_action_cents: 625_000, after_action_cents: 48_000, preventable_cents: 577_000, formula: "daily_delay_cost × expected_delay_days; after_action = inspection_cost", truth_class: "user_supplied_scenario" },
  dataset_url: "https://data.delaware.gov/Energy-and-Environment/Permitted-Septic-Systems/mv7j-tx3u",
  retrieved_at: "2026-09-01T20:00:00Z",
  limitation: "Application date is not proof of condition.",
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("LiveRecordCheck", () => {
  it("submits reviewer inputs and renders a fresh public result", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(result), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<LiveRecordCheck onBack={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/permit or parcel identifier/i), { target: { value: "0310-90S" } });
    fireEvent.change(screen.getByLabelText(/loan amount/i), { target: { value: "350000" } });
    fireEvent.click(screen.getByRole("button", { name: /run live record check/i }));

    expect(await screen.findByText("REVIEW DIFFERENCE")).toBeInTheDocument();
    expect(screen.getByText("$5,770")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /official DNREC record/i })).toHaveAttribute("href", result.record.official_detail_url);
    expect(fetchMock).toHaveBeenCalledWith("/api/v2/closing-rescue/public-record-check", expect.objectContaining({
      method: "POST",
      body: expect.stringContaining('"loan_amount_cents":35000000'),
    }));
  });

  it("states the privacy and simulation boundaries before submission", () => {
    render(<LiveRecordCheck onBack={vi.fn()} />);
    expect(screen.getByText(/owner and address fields are never requested/i)).toBeInTheDocument();
    expect(screen.getByText(/no booking or external action occurs/i)).toBeInTheDocument();
  });
});
