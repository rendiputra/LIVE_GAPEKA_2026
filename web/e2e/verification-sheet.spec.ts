// Regression test for the verification sheet's download button.
//
// The button did nothing because the embedded JSON was HTML-escaped: `"` became
// `&quot;`, which is a syntax error inside <script>, so no handler was attached.
// The sheet is a local file, so this spec navigates to file:// and does not use
// the preview server.

import { expect, test } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SHEET = resolve(HERE, "../../data/review/verification_sheet.html");
const SHEET_URL = `file://${SHEET}`;

test.describe("verification sheet", () => {
  test.skip(!existsSync(SHEET), "run `make verify-sheet` first");

  test("loads with no script errors and the download button works", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });

    await page.goto(SHEET_URL);
    await expect(page.locator("section.train")).toHaveCount(20);
    expect(errors).toEqual([]);

    // Mark a row wrong, record a note, and check the downloaded payload.
    const firstSection = page.locator("section.train").first();
    const row = firstSection.locator("tbody tr").nth(2);
    const note = row.locator(".row-note");
    await expect(note).toBeDisabled();
    await row.click();
    await expect(note).toBeEnabled();
    await note.fill("catatan uji");

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#download").click(),
    ]);
    expect(download.suggestedFilename()).toBe("verification_result.json");

    const path = await download.path();
    const payload = JSON.parse(readFileSync(path, "utf8"));
    expect(payload.trains).toHaveLength(20);
    expect(payload.selection_seed).toBeGreaterThan(0);

    const withErrors = payload.trains.filter(
      (train: { verdict: string }) => train.verdict === "has_errors",
    );
    expect(withErrors).toHaveLength(1);
    expect(withErrors[0].wrong_rows).toHaveLength(1);
    expect(withErrors[0].wrong_rows[0].note).toBe("catatan uji");
  });
});
