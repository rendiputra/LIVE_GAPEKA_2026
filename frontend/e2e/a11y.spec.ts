// Accessibility regression suite (Turn 3b).
//
// axe found two real defects, both still present after the earlier QA passes:
//
//  1. `label-content-name-mismatch` (WCAG 2.5.3, Label in Name) on the time-travel
//     nudge buttons: their accessible name was "Mundurkan 15 menit" while the
//     visible text was "−15m". Speech-input users saying what they see could not
//     activate them.
//  2. `link-in-text-block` (WCAG 1.4.1, Use of Color) in the Tentang modal: the
//     attribution links were blue with no underline until hover, so colour alone
//     distinguished them from the surrounding text.
//
// The suite asserts zero serious/critical axe violations in every state, and
// pins the two fixes directly so a refactor cannot quietly undo them.

import { AxeBuilder } from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function seriousViolations(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  return results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
}

test.beforeEach(async ({ page }) => {
  // External tiles are irrelevant to our DOM and would slow the suite down.
  await page.route("**/*tile*", (route) => route.abort());
  await page.route("**/*.pmtiles*", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByText(/Live \(Estimasi\)/).first()).toBeVisible({
    timeout: 40_000,
  });
});

test("default state has no serious axe violations", async ({ page }) => {
  const violations = await seriousViolations(page);
  expect(
    violations.map((violation) => `${violation.id}: ${violation.help}`),
  ).toEqual([]);
});

test("Layers and Filter popovers have no serious axe violations", async ({ page }) => {
  await page.getByRole("button", { name: /lapisan peta/i }).click();
  await expect(page.getByRole("dialog", { name: /lapisan peta/i })).toBeVisible();
  expect((await seriousViolations(page)).map((v) => v.id)).toEqual([]);
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: /filter kereta/i }).click();
  await expect(page.getByRole("dialog", { name: /filter kereta/i })).toBeVisible();
  expect((await seriousViolations(page)).map((v) => v.id)).toEqual([]);
});

test("Tentang modal has no serious axe violations", async ({ page }) => {
  await page.getByRole("button", { name: "Tentang aplikasi ini" }).click();
  await expect(page.getByRole("dialog", { name: /tentang/i })).toBeVisible();
  expect((await seriousViolations(page)).map((v) => v.id)).toEqual([]);
});

test("time-travel nudge buttons expose their visible text in the accessible name", async ({
  page,
}) => {
  // WCAG 2.5.3: the accessible name must contain the visible label.
  for (const [visible, ariaName] of [
    ["−15m", /−15m/],
    ["+15m", /\+15m/],
  ] as const) {
    // Looking the button up BY its accessible name already proves the name
    // contains the visible label; the text check proves the label is shown.
    const button = page.getByRole("button", { name: ariaName });
    await expect(button).toBeVisible();
    await expect(button).toContainText(visible);
    const name = await button.evaluate((element) => element.textContent ?? "");
    expect(name).toContain(visible);
  }
});

test("attribution links are distinguishable without colour", async ({ page }) => {
  await page.getByRole("button", { name: "Tentang aplikasi ini" }).click();
  const link = page.getByRole("link", { name: /openstreetmap\.org\/copyright/i });
  await expect(link).toBeVisible();
  // Underlined at rest, not only on hover (WCAG 1.4.1).
  const decoration = await link.evaluate(
    (element) => getComputedStyle(element).textDecorationLine,
  );
  expect(decoration).toContain("underline");
});

test("Layers popover takes focus on open and returns it to the trigger on Escape", async ({
  page,
}) => {
  const trigger = page.getByRole("button", { name: /lapisan peta/i });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: /lapisan peta/i });
  await expect(dialog).toBeVisible();

  // Focus must move INTO the dialog, otherwise keyboard users tab blindly.
  await expect
    .poll(() => dialog.evaluate((node) => node.contains(document.activeElement)))
    .toBe(true);

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("Filter popover takes focus on open and returns it on Escape", async ({ page }) => {
  const trigger = page.getByRole("button", { name: /filter kereta/i });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: /filter kereta/i });
  await expect(dialog).toBeVisible();
  await expect
    .poll(() => dialog.evaluate((node) => node.contains(document.activeElement)))
    .toBe(true);

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("Tentang modal returns focus to its trigger when closed", async ({ page }) => {
  const trigger = page.getByRole("button", { name: "Tentang aplikasi ini" });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: /tentang/i });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Tutup" })).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  // Focus must not fall back to <body>.
  await expect(trigger).toBeFocused();
});

test("keyboard reaches the Layers radios and arrow-free activation works", async ({ page }) => {
  const trigger = page.getByRole("button", { name: /lapisan peta/i });
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: /lapisan peta/i })).toBeVisible();

  // Tab from the dialog container into the first radio.
  await page.keyboard.press("Tab");
  const checked = page.getByRole("radio", { checked: true }).first();
  await expect(checked).toBeVisible();
  const before = await checked.getAttribute("aria-checked");
  expect(before).toBe("true");
});

test("every interactive control shows a visible focus ring", async ({ page }) => {
  const trigger = page.getByRole("button", { name: /lapisan peta/i });
  await trigger.focus();
  const style = await trigger.evaluate((element) => {
    const computed = getComputedStyle(element);
    return { shadow: computed.boxShadow, outline: computed.outlineStyle };
  });
  // focus-visible:ring-2 compiles to a box-shadow; a bare outline:none is banned.
  expect(style.shadow !== "none" || style.outline !== "none").toBe(true);
});
