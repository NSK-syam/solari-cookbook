import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SolariExecutionRail } from "./SolariExecutionRail";

describe("SolariExecutionRail", () => {
  it("shows durable verified receipts on the keyless public demo", () => {
    render(<SolariExecutionRail execution={null} busy={false} enabled={false} onRun={vi.fn()} />);

    const rail = screen.getByRole("complementary", { name: /Solari execution receipts/i });
    expect(within(rail).getByText("VERIFIED SOLARI RECEIPTS")).toBeInTheDocument();
    expect(within(rail).getAllByText("succeeded")).toHaveLength(3);
    expect(within(rail).queryByText("pending")).not.toBeInTheDocument();
    expect(within(rail).queryByText("blocked")).not.toBeInTheDocument();
    expect(within(rail).getByRole("status")).toHaveTextContent("Live walkthrough verified");
    expect(within(rail).queryByRole("button")).not.toBeInTheDocument();

    expect(within(rail).getByRole("link", { name: /Open calculation manifest/i })).toHaveAttribute(
      "href",
      "/proof/sandbox-manifest-bc4eed363440d4f5.json",
    );
    expect(within(rail).getByRole("link", { name: /View redacted capture/i })).toHaveAttribute(
      "href",
      "/proof/permit-record-redacted-c6f2c45ab0f8dee2.png",
    );
    expect(within(rail).getByRole("link", { name: /View desktop receipt/i })).toHaveAttribute(
      "href",
      "/proof/desktop-form-receipt-16f16b9891a9e289.png",
    );
  });

  it("keeps the live execution controls when Solari is configured", () => {
    render(<SolariExecutionRail execution={null} busy={false} enabled onRun={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Run live Solari proof" })).toBeEnabled();
    expect(screen.getAllByText("pending")).toHaveLength(2);
    expect(screen.getByText("blocked")).toBeInTheDocument();
  });
});
