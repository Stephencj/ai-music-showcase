import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { tab } from "./nav";

/**
 * Library folders UI. Safe against the live app: it only creates and removes
 * its own folders (named with a unique prefix) and only library entries it
 * added itself — blocks already in the library are never touched.
 */

const PREFIX = `PW ${Date.now().toString(36)}`;
let added: string[] = [];          // library entry ids this run created
let made: string[] = [];           // folder ids this run created

async function freshBlocks(request: APIRequestContext, n: number): Promise<string[]> {
  const blocks: { name: string }[] = await (await request.get("/api/blocks")).json();
  const { library } = await (await request.get("/api/library")).json();
  const inLib = new Set(library.map((e: { block_name: string }) => e.block_name));
  const free = blocks.map((b) => b.name).filter((b) => !inLib.has(b)).slice(0, n);
  expect(free.length, "need blocks that aren't in the library yet").toBe(n);
  return free;
}

async function folderByName(request: APIRequestContext, path: string) {
  const { folders } = await (await request.get("/api/library/folders")).json();
  return folders.find((f: { path: string }) => f.path === path);
}

async function folderItems(request: APIRequestContext, id: string): Promise<string[]> {
  const { folder } = await (await request.get(`/api/library/folders/${encodeURIComponent(id)}`)).json();
  return folder.items.map((e: { id: string }) => e.id);
}

async function cleanup(request: APIRequestContext) {
  // Match by id as well as prefix: a subfolder promoted to the top level
  // when its parent is deleted loses the prefix from its path.
  const { folders } = await (await request.get("/api/library/folders")).json();
  for (const f of folders) {
    if (f.path.startsWith(PREFIX) || made.includes(f.id)) {
      await request.delete(`/api/library/folders/${encodeURIComponent(f.id)}`);
    }
  }
  for (const id of added) await request.delete(`/api/library/${encodeURIComponent(id)}`);
  added = [];
  made = [];
}

async function openLibrary(page: Page) {
  await page.goto("/app/");
  await tab(page, /Library/);
  await expect(page.getByTestId("folder-tree")).toBeVisible();
}

const row = (page: Page, id: string) => page.locator(`[data-testid=folder-row][data-folder="${id}"]`);

test.afterEach(async ({ request }) => { await cleanup(request); });

test("folders: open in track order, drag to reorder, create/rename/note, move, delete",
  async ({ page, request }, info) => {
    const blocks = await freshBlocks(request, 3);
    const video = (await (await request.post("/api/library/folders", {
      data: { name: `${PREFIX} Christmas Mix`, description: "1-hour cozy mix" },
    })).json()).folder;
    const res = await request.post(`/api/library/folders/${video.id}/items`, { data: { block_names: blocks } });
    expect(res.ok()).toBeTruthy();
    made.push(video.id);
    const order0 = await folderItems(request, video.id);
    added.push(...order0);

    await openLibrary(page);
    await expect(row(page, video.id)).toContainText("3");
    await row(page, video.id).click();
    await expect(page.getByTestId("folder-head")).toContainText(`${PREFIX} Christmas Mix`);
    await expect(page.getByTestId("folder-note")).toHaveText("1-hour cozy mix");
    const cards = page.getByTestId("library-card");
    await expect(cards).toHaveCount(3);
    for (let i = 0; i < 3; i++) await expect(cards.nth(i)).toHaveAttribute("data-entry", order0[i]);
    // Each track keeps its play / sheet-music / Practice actions.
    await expect(cards.first().locator("audio")).toHaveAttribute("src", /\/audio$/);
    await expect(cards.first().getByTestId("view-pdf")).toHaveAttribute("href", /\/pdf\/full$/);
    await expect(cards.first().getByTestId("open-practice")).toBeVisible();
    await page.screenshot({ path: `test-screenshots/folders-open-${info.project.name}.png`, fullPage: true });

    // Drag the last track to the top.
    const handle = cards.nth(2).getByTestId("drag-handle");
    const target = cards.nth(0).getByTestId("drag-handle");
    await handle.scrollIntoViewIfNeeded();
    const from = (await handle.boundingBox())!;
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
    await page.mouse.down();
    await page.mouse.move(from.x + from.width / 2, from.y - 20, { steps: 5 });
    await target.scrollIntoViewIfNeeded();
    const to = (await target.boundingBox())!;
    await page.mouse.move(to.x + to.width / 2, to.y - 30, { steps: 15 });
    await page.mouse.up();
    const want = [order0[2], order0[0], order0[1]];
    await expect.poll(() => folderItems(request, video.id)).toEqual(want);
    for (let i = 0; i < 3; i++) await expect(cards.nth(i)).toHaveAttribute("data-entry", want[i]);

    // Subfolder via the app's prompt dialog.
    page.once("dialog", (d) => d.accept("Take 2"));
    await page.getByTestId("new-subfolder").click();
    await expect.poll(() => folderByName(request, `${PREFIX} Christmas Mix / Take 2`)).toBeTruthy();
    const sub = await folderByName(request, `${PREFIX} Christmas Mix / Take 2`);
    made.push(sub.id);
    await expect(page.getByTestId("folder-head")).toContainText("Take 2");
    await expect(row(page, sub.id)).toContainText("Take 2");

    // Rename + note on the subfolder.
    page.once("dialog", (d) => d.accept("Take Two"));
    await page.getByTestId("rename-folder").click();
    await expect(page.getByTestId("folder-head")).toContainText(`${PREFIX} Christmas Mix / Take Two`);
    page.once("dialog", (d) => d.accept("alt running order"));
    await page.getByTestId("describe-folder").click();
    await expect(page.getByTestId("folder-note")).toHaveText("alt running order");
    await expect(page.getByTestId("folder-empty")).toBeVisible();

    // Back in the video folder, move the first track into the subfolder.
    await row(page, video.id).click();
    await expect(cards).toHaveCount(3);
    await cards.first().getByTestId("move-to-folder").selectOption(sub.id);
    await expect(cards).toHaveCount(2);
    await expect(row(page, sub.id)).toContainText("1");
    expect(await folderItems(request, sub.id)).toEqual([want[0]]);
    expect(await folderItems(request, video.id)).toEqual([want[1], want[2]]);
    await page.screenshot({ path: `test-screenshots/folders-moved-${info.project.name}.png`, fullPage: true });

    // Delete the video folder via the confirm dialog: songs stay, sub moves up.
    page.once("dialog", (d) => d.accept());
    await page.getByTestId("delete-folder").click();
    await expect(row(page, video.id)).toHaveCount(0);
    await expect(row(page, sub.id)).toContainText("Take Two");
    const { library } = await (await request.get("/api/library")).json();
    for (const id of order0) expect(library.map((e: { id: string }) => e.id)).toContain(id);
    const { folder: unfiled } = await (await request.get("/api/library/folders/unfiled")).json();
    const unfiledIds = unfiled.items.map((e: { id: string }) => e.id);
    expect(unfiledIds).toContain(want[1]);
    expect(unfiledIds).toContain(want[2]);
  });

test("create a folder from the header and file a song from All songs", async ({ page, request }) => {
  const [block] = await freshBlocks(request, 1);
  const entry = (await (await request.post("/api/library", { data: { block_name: block } })).json()).saved;
  added.push(entry);

  await openLibrary(page);
  const name = `${PREFIX} New Video`;
  page.once("dialog", (d) => d.accept(name));
  await page.getByTestId("new-folder").click();
  await expect(page.getByTestId("folder-head")).toContainText(name);
  const f = await folderByName(request, name);
  expect(f).toBeTruthy();
  made.push(f.id);

  await row(page, "all").click();
  const card = page.locator(`[data-testid=library-card][data-entry="${entry}"]`);
  await card.getByTestId("move-to-folder").selectOption(f.id);
  await expect(row(page, f.id)).toContainText("1");
  await expect(card.locator(".pill", { hasText: name })).toBeVisible();
  expect(await folderItems(request, f.id)).toEqual([entry]);

  // Cancelling a prompt changes nothing.
  page.once("dialog", (d) => d.dismiss());
  await page.getByTestId("new-folder").click();
  await expect(page.getByTestId("folder-tree")).toBeVisible();
  expect((await (await request.get("/api/library/folders")).json()).folders
    .filter((x: { path: string }) => x.path.startsWith(PREFIX))).toHaveLength(1);
});
