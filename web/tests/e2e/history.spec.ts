import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { currentSessionId, deleteSessions, freshCreate, tab } from "./nav";

/**
 * Song history: threads live on the server. New song archives the thread
 * (no confirm), History reopens it where it was and the thread carries on;
 * every finished version is auto-saved as a block in the Practice pool (not
 * the Library) and its Practice button loads it. Library → Open in Timeline
 * opens a Christmas sample as v1 with its own sections, and a Timeline edit
 * on it makes v2 with the same seed; Library → Practice and Practice → Open
 * in Timeline link back. Cleans up only what it makes: its sessions (with
 * their auto-saved blocks) and any library entries it added. Screenshots
 * land in test-screenshots/<project>-history-*.png.
 */

const GEN_TIMEOUT = 300_000;

type Block = { name: string; tags?: string[]; created?: string; has_preview: boolean;
  spec?: { genre?: string; seed: number; tune?: string; sections?: { role: string }[] } | null;
  timeline?: { ok: boolean; reason?: string; session_id?: string } };
type Entry = { id: string; block_name: string };

const shot = (page: Page, name: string) =>
  page.screenshot({ path: `test-screenshots/${test.info().project.name}-history-${name}.png` });
const blocksOf = async (request: APIRequestContext) => (await (await request.get("/api/blocks")).json()) as Block[];
const libraryOf = async (request: APIRequestContext) =>
  ((await (await request.get("/api/library")).json()) as { library: Entry[] }).library;

// Library entries may name a block with spaces ("Xmas Original (Pop)"); blocks
// are stored with underscores. Compare the stored names.
const stored = (n: string) => n.trim().replace(/[/\\ ]/g, "_");

/** Put a block in the library unless it's there; returns the entry id to
 *  remove afterwards (null when it was already there: not ours to remove). */
async function ensureInLibrary(request: APIRequestContext, block: string): Promise<string | null> {
  if ((await libraryOf(request)).some((e) => stored(e.block_name) === stored(block))) return null;
  const r = await request.post("/api/library", { data: { block_name: block } });
  expect(r.ok()).toBeTruthy();
  return ((await r.json()) as { saved: string }).saved;
}

async function expectPracticeOn(page: Page, block: string) {
  await expect(page.locator("nav.tabbar").getByRole("button", { name: /Practice/ })).toHaveClass(/on/);
  const select = page.locator(".practice-controls select");
  await expect(select).toHaveValue(`block:${block}`, { timeout: 15_000 });
  await expect.poll(() => page.locator(".practice audio").first().evaluate((a) =>
    decodeURIComponent((a as HTMLAudioElement).getAttribute("src") ?? "")), { timeout: 15_000 })
    .toContain(`/api/blocks/${block}/audio`);
  await expect(page.locator(".practice-err")).toHaveCount(0);
}

test("new song archives the thread; History reopens it; each version is in Practice", async ({ page, request }) => {
  test.setTimeout(1_200_000);
  const sessions: (string | null)[] = [];
  const unexpected: string[] = [];
  page.on("dialog", (d) => {
    // Only rename (a prompt) and delete (a confirm) may ask anything.
    if (d.type() === "prompt") void d.accept("History test song");
    else if (d.type() === "confirm" && /^Delete/.test(d.message())) void d.accept();
    else { unexpected.push(d.message()); void d.dismiss(); }
  });
  try {
    await freshCreate(page);
    await page.getByTestId("session-input").fill("A calm funk fusion bed for a video, strings, 100 bpm");
    await page.getByTestId("session-input-send").click();
    await expect(page.getByTestId("version-1")).toHaveAttribute("data-status", "done", { timeout: GEN_TIMEOUT });
    const sid = await currentSessionId(page);
    sessions.push(sid);
    expect(sid).toBeTruthy();
    const title = (await page.getByTestId("session-title").textContent()) ?? "";
    expect(title).not.toContain("…");

    // v1 was saved as a block automatically: in Practice, not in the Library.
    const practice1 = page.getByTestId("practice-v1");
    await expect(practice1).toBeVisible({ timeout: 30_000 });
    const v1 = (await (await request.get(`/api/sessions/${sid}`)).json()).versions[0] as { block: string };
    expect(v1.block).toMatch(/_v1(_\d+)?$/);
    expect(v1.block).not.toContain("…");
    const b1 = (await blocksOf(request)).find((b) => b.name === v1.block)!;
    expect(b1.tags).toContain("auto-saved");
    expect(b1.has_preview).toBeTruthy();
    expect((await libraryOf(request)).some((e) => e.block_name === v1.block)).toBeFalsy();
    await shot(page, "session");

    // Session → Practice: that version, loaded.
    await practice1.click();
    await expectPracticeOn(page, v1.block);
    await expect(page.locator('.practice-controls optgroup[label="From Create"] option').first())
      .toHaveAttribute("value", `block:${v1.block}`);

    // New song archives it (no confirm) and starts a fresh thread.
    await tab(page, /Create/);
    await page.getByTestId("create-menu").click();
    await page.getByTestId("menu-new").click();
    await expect(page.getByTestId("session-title")).toHaveText("New song");
    await expect(page.getByTestId("msg-user")).toHaveCount(0);
    expect(unexpected, "New song asks nothing").toEqual([]);
    expect(await currentSessionId(page)).toBeNull();

    // History lists it; reopening it brings the thread back.
    await page.getByTestId("create-menu").click();
    await page.getByTestId("menu-history").click();
    const row = page.locator(`[data-testid="history-row"][data-session="${sid}"]`);
    await expect(row).toBeVisible({ timeout: 15_000 });
    await expect(row).toContainText(title);
    await expect(row).toContainText("1 version");
    await expect(row.getByTestId("history-play")).toBeEnabled();
    await shot(page, "list");
    await row.getByTestId("history-open").click();
    await expect(page.getByTestId("session-title")).toHaveText(title);
    await expect(page.getByTestId("version-1")).toHaveAttribute("data-status", "done");
    await expect(page.getByTestId("msg-describe")).toBeVisible();

    // …and carries on: the next version lands in the same session, same seed.
    const gen = page.waitForRequest((r) => r.url().endsWith("/api/generate") && r.method() === "POST",
      { timeout: GEN_TIMEOUT });
    await page.getByTestId("session-input").fill("simpler bass");
    await page.getByTestId("session-input-send").click();
    const body2 = JSON.parse((await gen).postData() || "{}") as { seed?: number };
    await expect(page.getByTestId("version-2")).toHaveAttribute("data-status", "done", { timeout: GEN_TIMEOUT });
    await expect(page.getByTestId("practice-v2")).toBeVisible({ timeout: 30_000 });
    const s = await (await request.get(`/api/sessions/${sid}`)).json();
    expect(s.versions).toHaveLength(2);
    expect(body2.seed).toBe(s.versions[0].seed);
    expect(await currentSessionId(page)).toBe(sid);

    // It survives a reload (the server holds it).
    await page.reload();
    await tab(page, /Create/);
    await expect(page.getByTestId("version-2")).toHaveAttribute("data-status", "done", { timeout: 15_000 });

    // Rename and delete from History.
    await page.getByTestId("create-menu").click();
    await page.getByTestId("menu-history").click();
    await row.getByTestId("history-rename").click();
    await expect(row).toContainText("History test song");
    await row.getByTestId("history-delete").click();
    await expect(row).toHaveCount(0);
    expect((await request.get(`/api/sessions/${sid}`)).status()).toBe(404);
    const left = (await blocksOf(request)).map((b) => b.name);
    for (const v of s.versions as { block: string }[]) expect(left).not.toContain(v.block);
    await expect(page.getByTestId("session-title")).toHaveText("New song");
  } finally {
    await deleteSessions(request, [...sessions, await currentSessionId(page)]);
  }
});

test("Library → Open in Timeline: a Christmas sample, edited into v2 with the same seed", async ({ page, request }) => {
  test.setTimeout(900_000);
  const added: string[] = [];
  const sessions: (string | null | undefined)[] = [];
  try {
    // A Christmas sample that isn't already one of your songs.
    const all = await blocksOf(request);
    const xmas = all.filter((b) => b.has_preview && b.spec?.genre?.startsWith("christmas_") && b.spec.tune
      && b.timeline?.ok && !b.timeline.session_id);
    const block = xmas.find((b) => b.name === "Xmas_Original_(Pop)") ?? xmas[0];
    expect(block, "a Christmas sample block").toBeTruthy();
    const id = await ensureInLibrary(request, block.name);
    if (id) added.push(id);
    // And one with no saved settings: its button is off, with the reason.
    const plain = all.find((b) => b.timeline && !b.timeline.ok && b.has_preview);
    if (plain) { const pid = await ensureInLibrary(request, plain.name); if (pid) added.push(pid); }

    await page.goto("/app/");
    await tab(page, /Library/);
    // The card carries the entry's own block name (may be spelled with spaces).
    const entryName = (await libraryOf(request)).find((e) => stored(e.block_name) === block.name)!.block_name;
    const card = page.locator(`[data-testid="library-card"][data-block="${entryName}"]`);
    await expect(card).toBeVisible({ timeout: 15_000 });
    if (plain) {
      const pn = (await libraryOf(request)).find((e) => stored(e.block_name) === plain.name)!.block_name;
      const pc = page.locator(`[data-testid="library-card"][data-block="${pn}"]`);
      await expect(pc.getByTestId("open-timeline")).toBeDisabled();
      await expect(pc.getByTestId("timeline-reason")).toContainText(/saved|guessed|available/);
    }

    // Library → Practice.
    await card.getByTestId("open-practice").click();
    await expectPracticeOn(page, block.name);

    // Library → Open in Timeline: v1 is the sample itself, with its sections.
    await tab(page, /Library/);
    await card.getByTestId("open-timeline").click();
    await expect(page.locator("nav.tabbar").getByRole("button", { name: /Create/ })).toHaveClass(/on/);
    const tl = page.getByTestId("timeline");
    await expect(tl).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("timeline-info")).toContainText("BPM", { timeout: 15_000 });
    const roles = (block.spec!.sections ?? []).map((x) => x.role);
    const secs = tl.locator(".ws-sec");
    await expect(secs).toHaveCount(roles.length);
    const sid = (await (await request.get("/api/blocks")).json() as Block[])
      .find((b) => b.name === block.name)!.timeline!.session_id;
    sessions.push(sid);
    expect(sid).toBeTruthy();
    const s1 = await (await request.get(`/api/sessions/${sid}`)).json();
    expect(s1.versions[0].block).toBe(block.name);
    expect(s1.versions[0].plan.seed).toBe(block.spec!.seed);
    await expect(page.getByTestId("timeline-play")).toBeEnabled();
    await expect.poll(() => tl.locator("[data-testid=timeline-wave] canvas").evaluateAll((cs) =>
      cs.filter((c) => (c as HTMLCanvasElement).width > 1).length), { timeout: 15_000 }).toBe(roles.length);
    await shot(page, "xmas-timeline");

    // A Timeline edit: remove the last section → v2, same seed and tune.
    const gen = page.waitForRequest((r) => r.url().endsWith("/api/generate") && r.method() === "POST",
      { timeout: GEN_TIMEOUT });
    await page.getByTestId(`sec-${roles.length - 1}`).click();
    await page.getByTestId("remove-section").click();
    const body = JSON.parse((await gen).postData() || "{}") as { seed?: number; tune?: string; remove_sections?: number[] };
    expect(body.seed).toBe(block.spec!.seed);
    expect(body.tune).toBe(block.spec!.tune);
    expect(body.remove_sections).toEqual([roles.length - 1]);
    await expect(page.locator(".ws-vpick")).toContainText("v2", { timeout: GEN_TIMEOUT });
    await expect(page.locator(".ws-tl-status")).toHaveCount(0, { timeout: GEN_TIMEOUT });
    await expect(secs).toHaveCount(roles.length - 1, { timeout: GEN_TIMEOUT });
    await expect.poll(async () => (await (await request.get(`/api/sessions/${sid}`)).json()).versions[1]?.block,
      { timeout: 60_000 }).toMatch(/_v2(_\d+)?$/);
    await shot(page, "xmas-v2");

    // Practice → Open in Timeline goes back to the same song.
    await tab(page, /Practice/);
    await page.getByTestId("practice-open-timeline").click();
    await expect(tl).toBeVisible();
    await expect(page.locator(".ws-vpick")).toContainText("v");
    expect(await currentSessionId(page)).toBe(sid);
  } finally {
    await deleteSessions(request, sessions);
    for (const id of added) await request.delete(`/api/library/${encodeURIComponent(id)}`);
  }
});
