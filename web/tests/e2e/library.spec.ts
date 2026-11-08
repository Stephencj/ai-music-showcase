import { test, expect, type APIRequestContext } from "@playwright/test";
import { openCreateMode, tab } from "./nav";

/**
 * Sheet-music library UI. Runs against the live server; seeds/cleans state
 * through the same /api the app uses. Screenshots land in test-screenshots/
 * for visual review.
 */

async function clearLibrary(request: APIRequestContext) {
  const res = await request.get("/api/library");
  const { library } = await res.json();
  for (const e of library) {
    await request.delete(`/api/library/${encodeURIComponent(e.id)}`);
  }
}

async function firstBlock(request: APIRequestContext): Promise<string> {
  const res = await request.get("/api/blocks");
  const blocks = await res.json();
  expect(blocks.length, "need at least one block on the server to test").toBeGreaterThan(0);
  return blocks[0].name;
}

type Page = import("@playwright/test").Page;


async function openLibraryTab(page: Page) {
  await page.goto("/app/");
  await tab(page, /Library/);
}

test.beforeEach(async ({ request }) => { await clearLibrary(request); });
test.afterAll(async ({ request }) => { await clearLibrary(request); });

test("empty state renders when the library has nothing", async ({ page }) => {
  await openLibraryTab(page);
  await expect(page.getByTestId("library-empty")).toBeVisible();
  await page.screenshot({ path: "test-screenshots/library-empty.png", fullPage: true });
});

test("a saved entry shows its actions; favorite persists; open jumps to Practice; remove clears it",
  async ({ page, request }) => {
    const block = await firstBlock(request);
    await request.post("/api/library", { data: { block_name: block, collection: "demo" } });

    await openLibraryTab(page);
    const card = page.getByTestId("library-card").first();
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute("data-block", block);

    // "View PDF" points at the inline full-score PDF (native viewer target).
    await expect(card.getByTestId("view-pdf")).toHaveAttribute("href", /\/pdf\/full$/);

    // Favorite toggles in the UI and persists to the backend.
    const fav = card.locator(".fav-btn");
    await expect(fav).toHaveAttribute("aria-pressed", "false");
    await fav.click();
    await expect(fav).toHaveAttribute("aria-pressed", "true");
    const lib = await (await request.get("/api/library")).json();
    expect(lib.library[0].favorite).toBe(true);

    await page.screenshot({ path: "test-screenshots/library-card.png", fullPage: true });

    // "Roll · Tab · Play" opens the Practice screen for that block.
    await card.getByTestId("open-practice").click();
    await expect(page.locator("nav.tabbar").getByRole("button", { name: /Practice/ }))
      .toHaveClass(/on/);

    // Remove empties the library.
    await tab(page, /Library/);
    page.once("dialog", (d) => d.accept());
    await page.getByTestId("remove-entry").first().click();
    await expect(page.getByTestId("library-empty")).toBeVisible();
  });

test("picking an instrument part updates the View PDF link before opening",
  async ({ page, request }) => {
    test.setTimeout(120_000); // first /parts call engraves the score (LilyPond)

    // Find a block that has at least one instrument part; this also warms the
    // server-side engraving cache so the in-app picker loads instantly.
    const blocks = await (await request.get("/api/blocks")).json();
    let block = "";
    let partId = "";
    for (const b of blocks.slice(0, 6)) {
      const res = await request.get(`/api/blocks/${encodeURIComponent(b.name)}/parts`);
      const inst = (await res.json()).parts.find((p: { id: string }) => p.id !== "full");
      if (inst) { block = b.name; partId = inst.id; break; }
    }
    expect(block, "need a block with instrument parts on the server").not.toBe("");

    await request.post("/api/library", { data: { block_name: block } });
    await openLibraryTab(page);
    const card = page.getByTestId("library-card").first();
    await expect(card).toBeVisible();

    // Default is the full score.
    await expect(card.getByTestId("view-pdf")).toHaveAttribute("href", /\/pdf\/full$/);

    // Open the picker (lazy-loads the parts), then choose an instrument.
    const select = card.getByTestId("part-select");
    await select.focus();
    await expect.poll(() => select.locator("option").count()).toBeGreaterThan(1);
    await select.selectOption(partId);

    // The View PDF link now targets that instrument's sheet music.
    await expect(card.getByTestId("view-pdf"))
      .toHaveAttribute("href", new RegExp(`/pdf/part/${partId}$`));
    await page.screenshot({ path: "test-screenshots/library-part-picker.png", fullPage: true });
  });

test("Save to Library from a Compose block surfaces it in the Library tab",
  async ({ page }) => {
    await page.goto("/app/");
    await openCreateMode(page, "blocks");

    // Expand the first block card, then save it to the library. The Compose
    // screen lazy-loads its block list from the live server, which can be slow
    // when the server is busy — allow generous time for the first card.
    const firstCard = page.locator(".tab-pane:not(.hidden) .block-card").first();
    await expect(firstCard).toBeVisible({ timeout: 25000 });
    await firstCard.getByRole("button", { name: "Details" }).click();
    const saveBtn = firstCard.getByTestId("save-to-library");
    await expect(saveBtn).toBeVisible();
    await saveBtn.click();
    await expect(saveBtn).toHaveText(/Saved/);

    // It now appears in the Library tab.
    await tab(page, /Library/);
    await expect(page.getByTestId("library-card")).toHaveCount(1);
    await page.screenshot({ path: "test-screenshots/library-from-compose.png", fullPage: true });
  });
