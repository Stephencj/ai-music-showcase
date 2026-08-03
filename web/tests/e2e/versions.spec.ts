import { test, expect } from "@playwright/test";

type Page = import("@playwright/test").Page;

/** Robust bottom-tab click (scoped to the tabbar; re-clicks past hydration). */
async function tab(page: Page, name: RegExp) {
  const btn = page.locator("nav.tabbar").getByRole("button", { name });
  await expect(btn).toBeVisible();
  await expect(async () => {
    await btn.click();
    await expect(btn).toHaveClass(/on/, { timeout: 1500 });
  }).toPass({ timeout: 15000 });
}

async function expandFirstBlock(page: Page) {
  await page.goto("/app/");
  await tab(page, /Compose/);
  const card = page.locator(".tab-pane:not(.hidden) .block-card").first();
  await expect(card).toBeVisible({ timeout: 25000 });
  await card.getByRole("button", { name: "Details" }).click();
  return card;
}

test("snapshot a block version, see it listed as active, then delete it",
  async ({ page }) => {
    const card = await expandFirstBlock(page);

    // Open the version history (lazy-loads).
    await card.getByTestId("history-toggle").click();
    const body = card.getByTestId("history-body");
    await expect(body).toBeVisible();

    // Snapshot the current state as a version.
    await body.getByTestId("snapshot-version").click();
    const row = body.getByTestId("version-row").first();
    await expect(row).toBeVisible();
    // A manual snapshot equals the live block, so it's the active version.
    await expect(row).toHaveAttribute("data-active", "1");
    await expect(row.getByTestId("restore-version")).toHaveText(/In use/);

    await card.screenshot({ path: "test-screenshots/block-versions.png" });

    // Clean up: delete the version (leaves the block content untouched).
    await row.getByTestId("delete-version").click();
    await expect(body.getByTestId("version-row")).toHaveCount(0);
  });
