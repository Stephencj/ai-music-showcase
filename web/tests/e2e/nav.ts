import { expect, type Page } from "@playwright/test";

/** Click a bottom-tab button, scoped to the tabbar so labels don't collide
 *  with in-screen buttons. Re-clicks until the tab is marked active, which
 *  guards against clicking before React hydrates. */
export async function tab(page: Page, name: RegExp) {
  const btn = page.locator("nav.tabbar").getByRole("button", { name });
  await expect(btn).toBeVisible();
  await expect(async () => {
    await btn.click();
    await expect(btn).toHaveClass(/on/, { timeout: 1500 });
  }).toPass({ timeout: 15000 });
}

/** Create → ⋯ → Advanced form (the full Generate form) or Blocks (the block
 *  builder, ex-Compose). */
export async function openCreateMode(page: Page, mode: "advanced" | "blocks") {
  await tab(page, /Create/);
  await page.getByTestId("create-menu").click();
  await page.getByTestId(`menu-${mode}`).click();
  await expect(page.locator(".ws-header.sub:visible .ws-name"))
    .toHaveText(mode === "advanced" ? "Advanced form" : "Blocks");
}
