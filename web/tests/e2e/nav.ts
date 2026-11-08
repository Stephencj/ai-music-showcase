import { expect, type APIRequestContext, type Page } from "@playwright/test";

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

/** Open the app on a fresh Create session (no thread in this browser). */
export async function freshCreate(page: Page) {
  await page.goto("/app/");
  await page.evaluate(() => {
    localStorage.removeItem("aimusic.create.session");
    localStorage.removeItem("aimusic.create.current");
  });
  await page.reload();
  await tab(page, /Create/);
}

/** The Create session this browser has open (its server id), if any. */
export const currentSessionId = (page: Page) =>
  page.evaluate(() => localStorage.getItem("aimusic.create.current"));

/** Delete sessions a test made: their threads and their auto-saved blocks
 *  (blocks saved to the library stay, so remove library entries first). */
export async function deleteSessions(request: APIRequestContext, ids: (string | null | undefined)[]) {
  for (const id of new Set(ids)) {
    if (id) await request.delete(`/api/sessions/${encodeURIComponent(id)}`);
  }
}
