/**
 * Fix 2: the layers popover must show which option is selected.
 *
 * The QA saw empty circles for every option, including the defaults. Root
 * cause: the popover is mounted twice (desktop cluster + mobile row) and both
 * instances used the same native radio `name`, so the browser treated them as
 * ONE group and unselected everything. The controls are now explicit ARIA
 * radios bound to store state.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

const DESKTOP = { width: 1280, height: 800 } as const;
const MOBILE = { width: 390, height: 844 } as const;

async function ready(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 30_000,
  });
}

async function openLayers(page: Page): Promise<Locator> {
  await page
    .getByRole("button", { name: "Lapisan peta" })
    .filter({ visible: true })
    .first()
    .click();
  const dialog = page
    .locator('div[role="dialog"][aria-label="Lapisan peta"]')
    .filter({ visible: true })
    .first();
  await expect(dialog).toBeVisible();
  return dialog;
}

function radio(dialog: Locator, label: string): Locator {
  return dialog.getByRole("radio", { name: label });
}

/** The selected indicator must actually paint, not just exist in the DOM. */
async function hasVisibleDot(control: Locator): Promise<boolean> {
  return control.evaluate((element) => {
    const dot = element.querySelector("span > span");
    if (!dot) return false;
    const rect = dot.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) return false;
    const style = getComputedStyle(dot);
    return style.backgroundColor !== "rgba(0, 0, 0, 0)" && style.display !== "none";
  });
}

for (const [label, viewport] of [
  ["desktop", DESKTOP],
  ["mobile", MOBILE],
] as const) {
  test.describe(`Fix 2 — ${label}`, () => {
    test.use({ viewport });

    test("defaults are visibly selected, and switching moves the indicator", async ({ page }) => {
      await ready(page);
      const dialog = await openLayers(page);

      const positron = radio(dialog, "Clean (Positron)");
      const liberty = radio(dialog, "Detail (Liberty)");
      const def = radio(dialog, "Default");
      const maxSpeed = radio(dialog, "Max Speed");

      // Fresh load: the defaults must be checked AND visibly marked.
      await expect(positron).toHaveAttribute("aria-checked", "true");
      await expect(def).toHaveAttribute("aria-checked", "true");
      await expect(liberty).toHaveAttribute("aria-checked", "false");
      await expect(maxSpeed).toHaveAttribute("aria-checked", "false");

      expect(await hasVisibleDot(positron)).toBe(true);
      expect(await hasVisibleDot(def)).toBe(true);
      expect(await hasVisibleDot(liberty)).toBe(false);

      // Choosing an option closes the popover, so each assertion reopens it.
      await maxSpeed.click();
      await expect(page.locator('aside[aria-label="Legenda overlay rel"]')).toBeVisible();

      const afterOverlay = await openLayers(page);
      await expect(radio(afterOverlay, "Max Speed")).toHaveAttribute("aria-checked", "true");
      await expect(radio(afterOverlay, "Default")).toHaveAttribute("aria-checked", "false");
      expect(await hasVisibleDot(radio(afterOverlay, "Max Speed"))).toBe(true);

      await radio(afterOverlay, "Detail (Liberty)").click();
      const afterBasemap = await openLayers(page);
      await expect(radio(afterBasemap, "Detail (Liberty)")).toHaveAttribute("aria-checked", "true");
      await expect(radio(afterBasemap, "Clean (Positron)")).toHaveAttribute("aria-checked", "false");
      expect(await hasVisibleDot(radio(afterBasemap, "Detail (Liberty)"))).toBe(true);
      // The overlay choice survived the basemap switch.
      await expect(radio(afterBasemap, "Max Speed")).toHaveAttribute("aria-checked", "true");
    });
  });
}