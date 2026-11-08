import { test, expect, type APIRequestContext, type Page, type Request } from "@playwright/test";
import { currentSessionId, deleteSessions, freshCreate, openCreateMode, tab } from "./nav";

/**
 * Create: the song workspace. Describe → v1 → a quick-change chip → v2 →
 * compare → save → open the timeline → toggle a section option → regenerate
 * just that section (same seed) → "What should change?" from the timeline →
 * Add block (hands the song's sections + the block to Blocks). Works with
 * whichever interpreter answers (Claude, the local AI or the rules). Cleans
 * up the library entry, the blocks it made and its session (with the
 * versions' auto-saved blocks). Screenshots land in
 * test-screenshots/<project>-*.png.
 */

type Body = Record<string, unknown> & { seed?: number; arrangement?: string; tempo?: number;
  section_overrides?: Record<string, { arrangement?: string }> };

const GEN_TIMEOUT = 300_000;


function nextGenerate(page: Page) {
  return page.waitForRequest((r) => r.url().endsWith("/api/generate") && r.method() === "POST",
    { timeout: GEN_TIMEOUT });
}
async function jobOf(req: Request) {
  return ((await (await req.response())!.json()) as { job_id: string }).job_id;
}
async function seedOf(request: APIRequestContext, id: string) {
  return ((await (await request.get(`/api/jobs/${id}`)).json()) as { result?: { seed: number } }).result?.seed;
}
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `test-screenshots/${test.info().project.name}-${name}.png` });

test("describe → v1 → quick change → v2 → compare → timeline → regenerate a section", async ({ page, request }) => {
  test.setTimeout(1_200_000);
  const made: { library: string[]; blocks: string[] } = { library: [], blocks: [] };
  try {
    await freshCreate(page);
    await expect(page.getByTestId("session-title")).toHaveText("New song");
    await expect(page.getByTestId("quick-quieter")).toBeDisabled();
    await expect(page.getByTestId("open-timeline")).toBeDisabled();

    // Describe → "Here's what I understood" + v1.
    let gen = nextGenerate(page);
    await page.getByTestId("session-input").fill(
      "A funk fusion background bed for a product video, horns and strings, sits quietly under narration, 120 bpm");
    await page.getByTestId("session-input-send").click();
    await expect(page.getByTestId("msg-user").first()).toContainText("funk fusion background bed");
    const described = page.getByTestId("msg-describe");
    await expect(described).toBeVisible({ timeout: GEN_TIMEOUT });
    await expect(described.getByTestId("plan-chips")).toContainText("Funk Fusion");
    const b1 = JSON.parse((await gen).postData() || "{}") as Body;
    expect(b1.genre).toBe("funk_fusion_full");
    const v1 = page.getByTestId("version-1");
    await expect(v1).toHaveAttribute("data-status", "done", { timeout: GEN_TIMEOUT });
    await expect(v1.locator(".wf-play")).toBeEnabled({ timeout: 30_000 });
    await expect(page.getByTestId("session-title")).toContainText("A funk fusion");
    await shot(page, "create-v1");
    const seed1 = await seedOf(request, await jobOf(await gen));
    expect(seed1).toBeTruthy();

    // A quick-change chip is feedback: "Simpler bass" → Changed N things → v2, same seed.
    gen = nextGenerate(page);
    await page.getByTestId("quick-simpler-bass").click();
    const revised = page.getByTestId("msg-revise");
    await expect(revised.getByTestId("changed-heading")).toHaveText(/Changed \d+ thing/, { timeout: GEN_TIMEOUT });
    await expect(revised.getByTestId("change-list")).toContainText(/simple bass/);
    const b2 = JSON.parse((await gen).postData() || "{}") as Body;
    expect(b2.seed).toBe(seed1);
    expect(b2.arrangement).toContain("simple_bass");
    await expect(page.getByTestId("version-2")).toHaveAttribute("data-status", "done", { timeout: GEN_TIMEOUT });
    await expect(page.getByTestId("version-2")).toHaveClass(/current/);

    // Compare v1 / v2 (A/B on one transport).
    await page.getByTestId("compare").click();
    const panel = page.getByTestId("compare-panel");
    await expect(panel).toBeVisible();
    await expect(page.getByTestId("compare-b")).toHaveAttribute("aria-pressed", "true");
    await page.getByTestId("compare-a").click();
    await expect(page.getByTestId("compare-a")).toHaveAttribute("aria-pressed", "true");

    // Save to library.
    await page.getByTestId("save-library").click();
    await expect(page.getByTestId("save-msg")).toContainText("Saved", { timeout: 30_000 });
    await expect(page.getByTestId("save-library")).toHaveText("Saved to library");
    const savedName = ((await page.getByTestId("save-msg").textContent()) ?? "").match(/“(.+)”/)?.[1];
    const lib = (await (await request.get("/api/library")).json()).library as { id: string; block_name: string; title: string }[];
    const entry = lib.find((e) => e.block_name === savedName);
    expect(entry, "the saved version is in the library").toBeTruthy();
    made.library.push(entry!.id); made.blocks.push(entry!.block_name);
    await shot(page, "create-v2");

    // The timeline: sections across, parts down.
    await page.getByTestId("open-timeline").click();
    const tl = page.getByTestId("timeline");
    await expect(tl).toBeVisible();
    await expect(page.getByTestId("timeline-info")).toContainText("BPM");
    const secs = tl.locator(".ws-sec");
    expect(await secs.count()).toBeGreaterThanOrEqual(3);
    await expect(page.getByTestId("lane-drums")).toBeVisible();
    await expect(page.getByTestId("lane-bass")).toBeVisible();
    await expect(page.getByTestId("lane-strings")).toBeVisible();
    // v2 has the simple bass everywhere.
    await expect(page.getByTestId("cell-bass-1")).toHaveText(/simple/);

    // Pick the chorus, toggle an option, regenerate just that section.
    const chorusIdx = (await secs.allTextContents()).findIndex((t) => /chorus/i.test(t));
    expect(chorusIdx).toBeGreaterThanOrEqual(0);
    const drumsBefore = (await page.getByTestId(`cell-drums-${chorusIdx - 1}`).textContent()) ?? "";
    await page.getByTestId(`sec-${chorusIdx}`).click();
    const sp = page.getByTestId("section-panel");
    await expect(sp).toContainText(/Chorus.*bars \d+–\d+/);
    await expect(page.getByTestId("regenerate-section")).toBeDisabled();
    await page.getByTestId("opt-pocket_drums").click();
    await expect(page.getByTestId("opt-pocket_drums")).toHaveAttribute("aria-pressed", "true");
    await shot(page, "timeline-section");
    gen = nextGenerate(page);
    await page.getByTestId("regenerate-section").click();
    const b3 = JSON.parse((await gen).postData() || "{}") as Body;
    expect(b3.seed).toBe(seed1);
    expect(b3.section_overrides?.chorus?.arrangement).toContain("pocket_drums");
    expect(b3.section_overrides?.chorus?.arrangement).toContain("simple_bass");   // the rest of the section kept
    expect(b3.arrangement).toBe(b2.arrangement);                                   // the song's arrangement untouched
    await expect(page.getByTestId("timeline-info")).toContainText("BPM", { timeout: GEN_TIMEOUT });
    await expect(page.locator(".ws-vpick")).toContainText("v3");
    await expect(page.getByTestId(`cell-drums-${chorusIdx}`)).toHaveText("pocket", { timeout: GEN_TIMEOUT });
    await expect(page.getByTestId(`cell-drums-${chorusIdx - 1}`)).toHaveText(drumsBefore);
    await expect(page.locator(".ws-tl-status")).toHaveCount(0, { timeout: GEN_TIMEOUT });

    // Transport plays the version; the playhead moves.
    await page.getByTestId("timeline-play").click();
    await expect(page.getByTestId("playhead")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("timeline-play")).toHaveAttribute("aria-label", "Pause", { timeout: 15_000 });
    await page.getByTestId("timeline-play").click();
    await shot(page, "timeline");

    // "What should change?" from the timeline → v4.
    gen = nextGenerate(page);
    await page.getByTestId("timeline-input").fill("slower");
    await page.getByTestId("timeline-input-send").click();
    const b4 = JSON.parse((await gen).postData() || "{}") as Body;
    expect(b4.tempo).toBeLessThan(120);
    expect(b4.section_overrides?.chorus?.arrangement).toContain("pocket_drums");
    await expect(page.locator(".ws-vpick")).toContainText("v4");
    await expect(page.locator(".ws-tl-status")).toHaveCount(0, { timeout: GEN_TIMEOUT });

    // Add block → the song's sections + the chosen block, opened in Blocks.
    const blocks = (await (await request.get("/api/blocks")).json()) as { name: string }[];
    const pick = blocks.find((b) => !made.blocks.includes(b.name))!;
    // The chorus stays selected across regenerations.
    await expect(page.getByTestId(`sec-${chorusIdx}`)).toHaveAttribute("aria-pressed", "true");
    const split = page.waitForResponse((r) => /\/api\/jobs\/[^/]+\/split$/.test(r.url()));
    await page.getByTestId("section-panel").locator(".ws-secondary").click();
    const popup = page.locator(".pf-popup");
    await expect(popup).toBeVisible();
    await popup.locator("input").fill(pick.name);
    await popup.getByRole("button", { name: pick.name }).first().click();
    const parts = ((await (await split).json()) as { section_blocks: string[] }).section_blocks;
    made.blocks.push(...parts);
    await expect(page.locator(".ws-header.sub:visible .ws-name")).toHaveText("Blocks");
    const items = page.locator(".tab-pane:not(.hidden) .tl-item");
    await expect(items).toHaveCount(parts.length + 1, { timeout: 15_000 });
    await expect(items.nth(chorusIdx + 1)).toContainText(pick.name);
    await shot(page, "add-block");

    // Back to the session: the thread kept everything, and survives a reload.
    await page.getByRole("button", { name: "Back to the session" }).last().click();
    await page.reload();
    await tab(page, /Create/);
    await expect(page.getByTestId("version-4")).toHaveAttribute("data-status", "done");
    await expect(page.getByTestId("msg-section")).toBeVisible();
  } finally {
    for (const id of made.library) await request.delete(`/api/library/${encodeURIComponent(id)}`);
    for (const b of made.blocks) await request.delete(`/api/blocks/${encodeURIComponent(b)}`);
    await deleteSessions(request, [await currentSessionId(page)]);
  }
});

test("Library, Practice and Band tabs, the Advanced form and Blocks still work", async ({ page, request }) => {
  // A library entry to open in Practice (removed again at the end).
  const blocks = (await (await request.get("/api/blocks")).json()) as { name: string }[];
  // Only a block that isn't in the library yet (the entry is deleted at the end).
  const inLib = new Set(((await (await request.get("/api/library")).json()).library as { id: string }[]).map((e) => e.id));
  let added: { id: string; block_name: string } | undefined;
  for (const b of blocks.filter((x) => !inLib.has(x.name))) {
    const r = await request.post("/api/library", { data: { block_name: b.name } });
    if (r.ok()) { added = (await r.json()).entry; break; }
  }
  expect(added, "a block that can go in the library").toBeTruthy();
  try {
  await page.goto("/app/");
  // Create is the first tab and the default.
  await expect(page.locator("nav.tabbar button")).toHaveText(["✨Create", "📚Library", "🎹Practice", "🎸Band"]);
  await expect(page.getByTestId("session")).toBeVisible();

  await tab(page, /Band/);
  await expect(page.locator(".band-start, .band-dash").first()).toBeVisible();
  // Library → Open in Practice still crosses tabs.
  await tab(page, /Library/);
  const card = page.locator(`[data-testid="library-card"][data-block="${added!.block_name}"]`);
  await expect(card).toBeVisible({ timeout: 15_000 });
  await card.getByTestId("open-practice").click();
  await expect(page.locator("nav.tabbar").getByRole("button", { name: /Practice/ })).toHaveClass(/on/);
  await expect(page.locator(".practice")).toBeVisible();

  // Advanced form = the full Generate form.
  await openCreateMode(page, "advanced");
  const adv = page.locator(".tab-pane:not(.hidden) .tab-pane:not(.hidden)");
  await expect(adv.locator(".genre-pick")).toBeVisible({ timeout: 15_000 });
  await expect(adv.getByTestId("band-card")).toBeVisible();
  await expect(adv.getByRole("button", { name: /Generate Song/ })).toBeEnabled();
  await shot(page, "advanced");

  // Blocks = the block builder (timeline + block library).
  await page.getByRole("button", { name: "Back to the session" }).first().click();
  await openCreateMode(page, "blocks");
  await expect(page.locator(".tab-pane:not(.hidden) .block-card").first()).toBeVisible({ timeout: 25_000 });
  } finally {
    await request.delete(`/api/library/${encodeURIComponent(added!.id)}`);
  }
});

test("Advanced form opens with the session's plan", async ({ page, request }) => {
  await page.addInitScript(() => {
    if (sessionStorage.getItem("seeded")) return;
    sessionStorage.setItem("seeded", "1");
    localStorage.setItem("aimusic.create.session", JSON.stringify({
      title: "Seeded song", msgs: [{ id: "u1", role: "user", text: "seeded" },
        { id: "a1", role: "app", kind: "describe", chips: ["Funk Fusion"], version: 1 }],
      versions: [{ n: 1, status: "error", error: "Interrupted", progress: 0, message: "", jobId: null,
        plan: { genre: "funk_fusion_full", tempo: 97, key: "D", scale: "minor" } }],
    }));
  });
  await page.goto("/app/");
  await expect(page.getByTestId("session-title")).toHaveText("Seeded song");
  await expect(page.getByTestId("version-1")).toHaveAttribute("data-status", "error");
  await openCreateMode(page, "advanced");
  const adv = page.locator(".tab-pane:not(.hidden) .tab-pane:not(.hidden)");
  await expect(adv.locator('input[type="number"]').first()).toHaveValue("97", { timeout: 15_000 });
  await expect(adv.locator(".keypick").first()).toContainText("D minor");
  // The browser's old thread moved to the server (and is cleaned up here).
  const sid = await currentSessionId(page);
  expect(sid).toBeTruthy();
  expect((await (await request.get(`/api/sessions/${sid}`)).json()).title).toBe("Seeded song");
  await deleteSessions(request, [sid]);
});

test("voice note: the recording is transcribed into the box", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "needs Chromium's fake microphone");
  // Speech-to-text itself is the gateway's (covered by the API test below);
  // here the server's answer is stubbed so the UI path is deterministic.
  await page.route("**/api/transcribe", (r) => r.fulfill({ json: { text: "make the bass simpler" } }));
  await page.goto("/app/");
  await tab(page, /Create/);
  await page.getByTestId("voice-note").click();
  await expect(page.locator(".ws-voice-note")).toContainText("Listening");
  await page.waitForTimeout(800);
  await page.getByTestId("voice-note").click();
  await expect(page.getByTestId("session-input")).toHaveValue("make the bass simpler", { timeout: 15_000 });
});

test("POST /api/transcribe reaches the gateway's speech-to-text", async ({ request }) => {
  // A tiny silent WAV: the gateway answers (possibly with empty text) or the
  // server says it's unavailable — never a crash.
  const sr = 16000, n = sr / 2, buf = Buffer.alloc(44 + n * 2);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write("WAVEfmt ", 8);
  buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(sr, 24); buf.writeUInt32LE(sr * 2, 28); buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34); buf.write("data", 36); buf.writeUInt32LE(n * 2, 40);
  const r = await request.post("/api/transcribe", {
    multipart: { file: { name: "note.wav", mimeType: "audio/wav", buffer: buf } }, timeout: 120_000,
  });
  expect([200, 503]).toContain(r.status());
  if (r.status() === 200) expect(typeof (await r.json()).text).toBe("string");
});
