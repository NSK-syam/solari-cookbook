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
  await page.getByRole("button", { name: "Start the rescue" }).click();

  await expect(page.getByText("47 active loans")).toBeVisible();
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
