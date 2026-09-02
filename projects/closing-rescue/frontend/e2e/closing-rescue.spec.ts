import { expect, test } from "@playwright/test";

test("runs, approves, reloads, and preserves the cinematic rescue", async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const failedRequests: string[] = [];

  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    if (response.url().includes("/api/") && response.status() >= 400) {
      failedRequests.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto("/");
  await page.getByRole("button", { name: /Start the rescue/ }).click();

  await expect(page.getByText("47 active loans")).toBeVisible();
  const realMap = page.getByRole("region", { name: /interactive real map/i });
  await expect(realMap).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Pause story" }).click();
  await expect(realMap).toHaveAttribute("data-map-status", "ready", { timeout: 15_000 });
  await expect(realMap.getByText("MILTON, DELAWARE")).toBeVisible();
  await expect(realMap.getByText(/synthetic demonstration.*exact parcel not displayed/i)).toBeVisible();
  await expect(realMap.getByRole("link", { name: /OpenStreetMap contributors/i })).toBeVisible();
  await page.getByRole("button", { name: "Resume story" }).click();

  await expect(page.getByText("Show assumptions and limitations")).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Pause story" }).click();
  await page.getByText("Show assumptions and limitations").click();
  await expect(page.getByText(/\$24,000 × 75% = \$18,000/)).toBeVisible();
  await expect(page.getByText(/\(\$24,000 × 18%\) \+ \$480 = \$4,800/)).toBeVisible();
  await page.getByRole("button", { name: "Resume story" }).click();

  await expect(page.getByText("First State Environmental")).toBeVisible();
  await expect(page.getByText("$480")).toBeVisible();

  await page.locator("button:visible").filter({ hasText: "Open evidence ledger" }).click();
  const ledger = page.getByRole("dialog");
  await expect(ledger.getByText("Mireye · location")).toBeVisible();
  await expect(ledger.getByRole("link", { name: /Recorded fixture response/ })).toBeVisible();
  await expect(ledger.getByText("Delaware Open Data · septic permit")).toBeVisible();
  await expect(ledger.getByRole("link", { name: /Recorded Permitted Septic Systems query/ })).toBeVisible();
  await ledger.getByRole("button", { name: "Close evidence ledger" }).click();

  await page.getByRole("button", { name: "Approve rescue" }).click();
  await expect(page.getByText(/Rescue completed/).first()).toBeVisible();
  await expect(page.getByText("$13,200")).toBeVisible();

  await page.reload();
  await expect(page.getByText(/Rescue completed/).first()).toBeVisible();
  await expect(page.getByText("$13,200")).toBeVisible();

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
  expect(failedRequests).toEqual([]);

  await page.screenshot({
    path: testInfo.outputPath(`${testInfo.project.name}-closing-rescue.png`),
    fullPage: true,
  });
});

test("checks a reviewer-supplied public record and scenario", async ({ page }) => {
  await page.route("**/api/v2/closing-rescue/public-record-check", async (route) => {
    const submitted = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query_type: submitted.identifier_type,
        query_value: submitted.identifier,
        comparison: "needs_review",
        summary: "The submitted year differs from the public record's application-received year; verify the underlying documents.",
        claimed_year: submitted.claimed_year,
        official_record_year: 1990,
        closing_date: submitted.closing_date,
        days_to_close: 12,
        matching_record_count: 1,
        record: { permit_number: submitted.identifier, parcel_reference: "1-34-07.00-0430.00", application_received_date: "1990-06-28", permit_status: "Completion Report Received", system_type: "Gravity", construction_type: "New Construction", county: "Sussex", official_detail_url: "https://den.dnrec.delaware.gov/Detail/PermitDetail.aspx?id=60484984" },
        exposure: { loan_amount_cents: submitted.loan_amount_cents, daily_delay_cost_cents: submitted.daily_delay_cost_cents, expected_delay_days: submitted.expected_delay_days, inspection_cost_cents: submitted.inspection_cost_cents, without_action_cents: 900_000, after_action_cents: 55_000, preventable_cents: 845_000, formula: "daily_delay_cost × expected_delay_days; after_action = inspection_cost", truth_class: "user_supplied_scenario" },
        dataset_url: "https://data.delaware.gov/Energy-and-Environment/Permitted-Septic-Systems/mv7j-tx3u",
        retrieved_at: "2026-09-01T20:00:00Z",
        limitation: "A public permit application date is not proof of installation, replacement, system condition, or regulatory compliance. Confirm differences with DNREC.",
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Check a real public record" }).click();
  await page.getByLabel(/Permit or parcel identifier/).fill("0310-90S");
  await page.getByLabel(/Loan amount/).fill("525000");
  await page.getByLabel(/Daily delay cost/).fill("1800");
  await page.getByLabel(/Expected delay/).fill("5");
  await page.getByLabel(/Inspection estimate/).fill("550");
  await page.getByRole("button", { name: "Run live record check" }).click();

  await expect(page.getByText("REVIEW DIFFERENCE")).toBeVisible();
  await expect(page.getByText("$525,000")).toBeVisible();
  await expect(page.getByText("$8,450")).toBeVisible();
  await expect(page.getByRole("link", { name: /official DNREC record/ })).toBeVisible();
});
