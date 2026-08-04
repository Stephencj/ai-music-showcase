import { test, expect } from "@playwright/test";

/**
 * Band-aware generation on the Generate screen: a quick inline band maker and
 * loading a saved band from the Band game (localStorage). An active band
 * supersedes the Genre picker. Screenshots land in test-screenshots/.
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

test("quick band maker: add members, set genres, band supersedes the Genre card", async ({ page }) => {
  await page.goto("/app/");
  await tab(page, /Generate/);

  // Turn on band mode.
  await page.getByTestId("band-toggle").click();
  await expect(page.getByTestId("band-add")).toBeVisible();

  // Add two members; give them a genre each.
  await page.getByTestId("band-add").click();
  await page.getByTestId("band-add").click();
  const members = page.getByTestId("band-member");
  await expect(members).toHaveCount(2);
  for (let i = 0; i < 2; i++) {
    // Pick the first real genre option (index 0 is the "Genre…" placeholder).
    await members.nth(i).getByTestId("band-member-genre").selectOption({ index: 1 });
  }

  // The summary reflects the roster + resolved genre, and the Genre card is
  // marked superseded.
  const summary = page.getByTestId("band-summary");
  await expect(summary).toContainText(/instrument/);
  await expect(summary).not.toContainText("pick a member genre");
  await expect(page.locator(".card.superseded")).toBeVisible();

  await page.screenshot({ path: "test-screenshots/band-generate.png", fullPage: true });
});

test("load a saved band from the Band game populates the roster", async ({ page }) => {
  // Seed a band the way the Band game persists it (localStorage) before load.
  await page.addInitScript(() => {
    localStorage.setItem("aimusic.band", JSON.stringify({
      name: "The Testers", fans: 0, money: 0, gigs: 0,
      members: [
        { id: "m1", name: "Ava", part: "Vocals", genre: "rock_anthem_full", body: "girl" },
        { id: "m2", name: "Bo", part: "Bass", genre: "funk_full_song", body: "boy" },
        { id: "m3", name: "Cy", part: "Guitar", genre: "rock_anthem_full", body: "boy" },
      ],
    }));
  });
  await page.goto("/app/");
  await tab(page, /Generate/);

  await page.getByTestId("band-toggle").click();
  await page.getByTestId("band-load").click();

  await expect(page.getByTestId("band-member")).toHaveCount(3);
  const summary = page.getByTestId("band-summary");
  // Vocalist sets the overarching genre (Rock); 3 parts → 3 instruments.
  await expect(summary).toContainText("3 instruments");
  await expect(summary).toContainText(/base genre:\s*Rock/);
  // The funk bassist colours the verse (blend on by default).
  await expect(summary).toContainText(/Verse/);
  await expect(summary).toContainText(/Funk/);
  await page.screenshot({ path: "test-screenshots/band-blend.png", fullPage: true });

  // Toggling blend off drops the per-section colouring.
  await page.getByTestId("band-blend").click();
  await expect(summary).not.toContainText("section blend");
});
