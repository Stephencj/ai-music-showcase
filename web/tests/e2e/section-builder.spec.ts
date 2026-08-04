import { test, expect } from "@playwright/test";

/**
 * Section-by-section builder (Generate screen): per-section chord progression
 * + instrument subset. Runs against the live server; screenshots land in
 * test-screenshots/ for visual review. Uses the "Rock" genre, whose
 * rock_anthem_full preset ships verse/chorus/bridge progression pools.
 */

type Page = import("@playwright/test").Page;

async function tab(page: Page, name: RegExp) {
  const btn = page.locator("nav.tabbar").getByRole("button", { name });
  await expect(btn).toBeVisible();
  await expect(async () => {
    await btn.click();
    await expect(btn).toHaveClass(/on/, { timeout: 1500 });
  }).toPass({ timeout: 15000 });
}

/** Open the genre wheel and pick a genre by family + genre name. The wheel only
 *  renders the active family's genre buttons, so activate the family arc first. */
async function pickGenre(page: Page, family: RegExp, genre: RegExp) {
  await page.locator(".tab-pane:not(.hidden) .genre-pick").click();
  const popup = page.locator(".gw-popup");
  await expect(popup).toBeVisible();
  // Click family arcs until the target genre button appears, then click it.
  await expect(async () => {
    const arc = popup.locator('svg [role="button"]').filter({ hasText: family });
    if (await arc.count()) await arc.first().click();
    const gbtn = popup.locator(".gw-genre", { hasText: genre });
    await expect(gbtn).toBeVisible({ timeout: 1000 });
    await gbtn.click();
  }).toPass({ timeout: 12000 });
  await expect(popup).toBeHidden();
}

test("per-section chord progression + instrument subset controls work", async ({ page }) => {
  await page.goto("/app/");
  await tab(page, /Generate/);

  // Choose Rock (rock_anthem_full → has verse/chorus/bridge progression pools).
  await pickGenre(page, /Rock|Metal/, /^Rock$/);
  await expect(page.locator(".tab-pane:not(.hidden) .genre-name")).toHaveText(/Rock/);

  // Open the Chorus section's advanced (⋯) panel.
  const advBtn = page.getByTestId("sec-adv-chorus");
  await expect(advBtn).toBeVisible();
  await advBtn.click();

  // --- Per-section CHORD PROGRESSION ---
  const prog = page.getByTestId("sec-prog-chorus");
  await expect(prog).toBeVisible();
  // Auto + at least a couple of pooled options.
  await expect.poll(() => prog.locator("option").count()).toBeGreaterThan(2);
  const optionValues = await prog.locator("option").evaluateAll(
    (opts) => opts.map((o) => (o as HTMLOptionElement).value).filter(Boolean));
  expect(optionValues.length).toBeGreaterThan(0);
  await prog.selectOption(optionValues[0]);
  // The section row shows a 🎼 progression badge reflecting the choice. Scope
  // the row by its ⋯ testid — hasText "Chorus" would also match "Pre-chorus".
  const chorusRow = page.locator(".section-row")
    .filter({ has: page.getByTestId("sec-adv-chorus") });
  await expect(chorusRow.locator(".section-badge", { hasText: "🎼" })).toBeVisible();

  // --- Per-section INSTRUMENT subset ---
  const plays = page.getByTestId("sec-plays-chorus");
  await expect(plays).toBeVisible();
  const chips = plays.locator("button.chip");
  const nChips = await chips.count();
  expect(nChips).toBeGreaterThan(1);
  // Drop one instrument from the chorus; a 🎛 instrument-count badge appears.
  await chips.nth(1).click();
  await expect(chorusRow.locator(".section-badge", { hasText: "🎛" })).toBeVisible();

  await page.screenshot({ path: "test-screenshots/section-builder.png", fullPage: true });
});
