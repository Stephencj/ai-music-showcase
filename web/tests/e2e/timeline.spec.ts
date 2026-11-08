import { test, expect, type Page, type Request } from "@playwright/test";
import { currentSessionId, deleteSessions, freshCreate } from "./nav";

/**
 * Create → Timeline: the waveform transport (tap/drag to scrub, ▶ from a
 * section, a header jumps while playing) and the silencing edits — silence a
 * part in one section, remove a part from the song (and bring it back),
 * remove a section — each a new version with the same seed, Undo going back.
 * Deletes its session at the end (with the versions' auto-saved blocks); makes
 * no library entries. Screenshots land in
 * test-screenshots/<project>-timeline-*.png.
 */

type Body = Record<string, unknown> & { seed?: number; instruments?: string[]; remove_sections?: number[];
  section_overrides?: Record<string, { instruments?: string[] }> };
type Peaks = { peaks: number[]; duration: number; section_starts: number[] };

const GEN_TIMEOUT = 300_000;

function nextGenerate(page: Page) {
  return page.waitForRequest((r) => r.url().endsWith("/api/generate") && r.method() === "POST",
    { timeout: GEN_TIMEOUT });
}
async function jobOf(req: Request) {
  return ((await (await req.response())!.json()) as { job_id: string }).job_id;
}
const bodyOf = (req: Request) => JSON.parse(req.postData() || "{}") as Body;
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `test-screenshots/${test.info().project.name}-timeline-${name}.png` });
const audioTime = (page: Page) =>
  page.evaluate(() => document.querySelector<HTMLAudioElement>("[data-testid=timeline] audio")!.currentTime);
const audioPaused = (page: Page) =>
  page.evaluate(() => document.querySelector<HTMLAudioElement>("[data-testid=timeline] audio")!.paused);

async function versionDone(page: Page, n: number) {
  await expect(page.locator(".ws-vpick")).toContainText(`v${n}`, { timeout: GEN_TIMEOUT });
  await expect(page.locator(".ws-tl-status")).toHaveCount(0, { timeout: GEN_TIMEOUT });
  await expect(page.getByTestId("timeline-info")).toContainText("BPM", { timeout: GEN_TIMEOUT });
}

test("timeline: scrub the waveform, play from a section, silence a part / a cell / a section, undo", async ({ page, request }) => {
  test.setTimeout(1_500_000);
  await freshCreate(page);
  try {
    // v1.
    let gen = nextGenerate(page);
    await page.getByTestId("session-input").fill(
      "A funk fusion background bed for a product video, horns and strings, sits quietly under narration, 120 bpm");
    await page.getByTestId("session-input-send").click();
    const r1 = await gen;
    expect(bodyOf(r1).genre).toBe("funk_fusion_full");
    await expect(page.getByTestId("version-1")).toHaveAttribute("data-status", "done", { timeout: GEN_TIMEOUT });
    const job1 = await jobOf(r1);
    const seed1 = ((await (await request.get(`/api/jobs/${job1}`)).json()) as { result: { seed: number } }).result.seed;
    expect(seed1).toBeTruthy();

    await page.getByTestId("open-timeline").click();
    const tl = page.getByTestId("timeline");
    await expect(tl).toBeVisible();
    const secs = tl.locator(".ws-sec");
    const names = await secs.allTextContents();
    const nSecs = names.length;
    const verse = names.findIndex((t) => /verse/i.test(t));
    const chorus = names.findIndex((t) => /chorus/i.test(t));
    const bridge = names.findIndex((t) => /brdg/i.test(t));
    expect(verse).toBeGreaterThanOrEqual(0);
    expect(chorus).toBeGreaterThan(verse);
    expect(bridge).toBeGreaterThan(chorus);

    // ---- the waveform transport --------------------------------------------
    const wave = page.getByTestId("timeline-wave");
    await expect(wave).toBeVisible();
    const peaks = (await (await request.get(`/api/jobs/${job1}/peaks`)).json()) as Peaks;
    expect(peaks.peaks.length).toBeGreaterThan(100);
    expect(peaks.section_starts).toHaveLength(nSecs);
    // The waveform is drawn into each section's column.
    await expect.poll(() => wave.locator("canvas").evaluateAll((cs) =>
      cs.filter((c) => (c as HTMLCanvasElement).width > 1).length)).toBe(nSecs);
    await expect(tl.locator(".ws-times span").last()).not.toHaveText("0:00", { timeout: 30_000 });
    const end = (i: number) => (i + 1 < nSecs ? peaks.section_starts[i + 1] : peaks.duration);

    // Tap the middle of the chorus column → the chorus, about halfway through.
    const col = wave.locator(".ws-wave-sec");
    const cb = (await col.nth(chorus).boundingBox())!;
    await page.mouse.click(cb.x + cb.width / 2, cb.y + cb.height / 2);
    let at = await audioTime(page);
    const mid = (peaks.section_starts[chorus] + end(chorus)) / 2;
    expect(at).toBeGreaterThan(peaks.section_starts[chorus]);
    expect(at).toBeLessThan(end(chorus));
    expect(Math.abs(at - mid)).toBeLessThan((end(chorus) - peaks.section_starts[chorus]) * 0.15);
    await expect(page.getByTestId("playhead")).toBeVisible();
    const headAt = async () => Number((await page.getByTestId("playhead").getAttribute("style"))!.match(/left:\s*([\d.]+)/)![1]);
    const head1 = await headAt();

    // Drag from the intro to the bridge: the playhead follows.
    const ib = (await col.nth(0).boundingBox())!, bb = (await col.nth(bridge).boundingBox())!;
    await page.mouse.move(ib.x + 4, ib.y + ib.height / 2);
    await page.mouse.down();
    expect(await audioTime(page)).toBeLessThan(end(0));
    await page.mouse.move(bb.x + bb.width * 0.25, bb.y + bb.height / 2, { steps: 8 });
    await page.mouse.up();
    at = await audioTime(page);
    expect(at).toBeGreaterThan(peaks.section_starts[bridge]);
    expect(at).toBeLessThan(end(bridge));
    expect(await headAt()).toBeGreaterThan(head1);
    await shot(page, "scrub");

    // ▶ From here: the chorus plays from its first beat.
    await page.getByTestId(`sec-${chorus}`).click();
    await page.getByTestId("play-from-section").click();
    await expect(page.getByTestId("timeline-play")).toHaveAttribute("aria-label", "Pause", { timeout: 15_000 });
    at = await audioTime(page);
    expect(at).toBeGreaterThanOrEqual(peaks.section_starts[chorus] - 0.05);
    expect(at).toBeLessThan(peaks.section_starts[chorus] + 2);
    // While playing, a section header jumps there too.
    await page.getByTestId("sec-0").click();
    at = await audioTime(page);
    expect(at).toBeLessThan(2);
    expect(await audioPaused(page)).toBe(false);
    await page.getByTestId("timeline-play").click();
    await expect(page.getByTestId("timeline-play")).toHaveAttribute("aria-label", "Play");

    // ---- silence the bass in the verse (one cell) ---------------------------
    await page.getByTestId(`cell-bass-${verse}`).click();
    await expect(page.getByTestId("silence-here")).toHaveText("Silence bass here");
    gen = nextGenerate(page);
    await page.getByTestId("silence-here").click();
    const b2 = bodyOf(await gen);
    expect(b2.seed).toBe(seed1);
    const mask = b2.section_overrides?.verse?.instruments ?? [];
    expect(mask).not.toContain("electric_bass");
    expect(mask).toContain("drum_kit");
    await versionDone(page, 2);
    await expect(page.getByTestId(`cell-bass-${verse}`)).toHaveText("rests");
    await expect(page.getByTestId(`cell-bass-${chorus}`)).not.toHaveText("rests");
    await expect(page.getByTestId(`cell-drums-${verse}`)).not.toHaveText(/^(rests)?$/);
    // (The cell stays selected across the regeneration.)
    await expect(page.getByTestId("silence-here")).toHaveText("Bring bass back here");
    await shot(page, "silenced-cell");

    // ---- remove the keys from the whole song --------------------------------
    await page.getByTestId("lane-name-keys").click();
    const lp = page.getByTestId("lane-panel");
    await expect(lp).toContainText("Keys · whole song");
    gen = nextGenerate(page);
    await page.getByTestId("lane-remove").click();
    const b3 = bodyOf(await gen);
    expect(b3.seed).toBe(seed1);
    expect(b3.instruments).not.toContain("electric_piano");
    expect(b3.instruments).toContain("drum_kit");
    expect(b3.section_overrides?.verse?.instruments).not.toContain("electric_piano");
    expect(b3.section_overrides?.verse?.instruments).not.toContain("electric_bass");  // the verse rest kept
    await versionDone(page, 3);
    await expect(page.getByTestId("lane-keys")).toHaveClass(/muted/);
    await expect(page.getByTestId("lane-keys").locator(".ws-cell:not(.off)")).toHaveCount(0);
    await page.getByTestId("lane-name-keys").click();
    await expect(page.getByTestId("lane-restore")).toHaveText("Bring keys back");
    await shot(page, "removed-lane");
    await page.getByTestId("lane-name-keys").click();
    await expect(lp).toHaveCount(0);

    // ---- remove the bridge --------------------------------------------------
    await page.getByTestId(`sec-${bridge}`).click();
    gen = nextGenerate(page);
    await page.getByTestId("remove-section").click();
    const b4 = bodyOf(await gen);
    expect(b4.seed).toBe(seed1);
    expect(b4.remove_sections).toEqual([bridge]);
    expect(b4.instruments).not.toContain("electric_piano");
    await versionDone(page, 4);
    await expect(secs).toHaveCount(nSecs - 1);
    const after = await secs.allTextContents();
    expect(after.filter((t) => /brdg/i.test(t))).toHaveLength(0);
    expect(after.filter((t) => /chorus/i.test(t))).toHaveLength(names.filter((t) => /chorus/i.test(t)).length);
    await expect(page.getByTestId(`cell-bass-${verse}`)).toHaveText("rests");
    await expect(page.getByTestId("lane-keys")).toHaveClass(/muted/);
    await shot(page, "removed-section");

    // Every edit was a version: Undo walks back through them.
    await page.getByTestId("timeline-undo").click();
    await expect(page.locator(".ws-vpick")).toContainText("v3");
    await expect(secs).toHaveCount(nSecs);
    await page.getByTestId("timeline-undo").click();
    await expect(page.locator(".ws-vpick")).toContainText("v2");
    await expect(page.getByTestId("lane-keys")).not.toHaveClass(/muted/);
    await expect(page.getByTestId(`cell-bass-${verse}`)).toHaveText("rests");
    // The thread has a message per edit.
    await page.getByTestId("timeline-back").click();
    await expect(page.getByTestId("msg-section")).toHaveCount(3);
    await expect(page.getByTestId("version-4")).toHaveAttribute("data-status", "done");
  } finally {
    await deleteSessions(request, [await currentSessionId(page)]);
  }
});

test("timeline: a choir carol — Choir lane, \"on\" labels, rests where the form leaves a part out, move the tune when silencing", async ({ page }) => {
  test.setTimeout(1_500_000);
  await freshCreate(page);
  try {
    let gen = nextGenerate(page);
    await page.getByTestId("session-input").fill("Church choir Silent Night, background, about a minute");
    await page.getByTestId("session-input-send").click();
    const r1 = await gen;
    const b1 = bodyOf(r1);
    expect(b1.genre).toBe("christmas_choir_full");
    await expect(page.getByTestId("version-1")).toHaveAttribute("data-status", "done", { timeout: GEN_TIMEOUT });

    await page.getByTestId("open-timeline").click();
    const tl = page.getByTestId("timeline");
    await expect(tl).toBeVisible();
    await expect(page.getByTestId("timeline-info")).toContainText("BPM", { timeout: GEN_TIMEOUT });
    const names = await tl.locator(".ws-sec").allTextContents();
    const chorus = names.findIndex((t) => /chorus/i.test(t));
    const intro = names.findIndex((t) => /intro/i.test(t));
    expect(chorus).toBeGreaterThanOrEqual(0);
    expect(intro).toBe(0);

    // The choir is its own lane (not folded into Keys with the organ).
    const choir = page.getByTestId("lane-choir");
    await expect(choir).toBeVisible();
    await expect(choir).not.toHaveClass(/muted/);
    await expect(page.getByTestId("lane-name-choir")).toHaveText("Choir");
    await expect(page.getByTestId(`cell-choir-${chorus}`)).toHaveText("on");
    await expect(page.getByTestId("lane-keys")).toBeVisible();
    // Christmas cells say "on", never Funk Fusion's part names.
    await expect(page.getByTestId(`cell-keys-${chorus}`)).toHaveText("on");
    const labels = await tl.locator(".ws-cell").allTextContents();
    expect(labels.filter((t) => /chops|groove|slap|riffs|pad|hits|lead/.test(t))).toEqual([]);
    // The choir doesn't sing the intro (the organ has it): a resting cell,
    // dimmer, in the lane's colour.
    const introChoir = page.getByTestId(`cell-choir-${intro}`);
    await expect(introChoir).toHaveText("rests");
    await expect(introChoir).toHaveClass(/rest/);
    await expect(introChoir).not.toHaveClass(/\boff\b/);
    expect(Number(await introChoir.evaluate((e) => getComputedStyle(e).opacity))).toBeLessThan(0.7);
    await expect(page.getByTestId(`cell-keys-${intro}`)).toHaveText("on");
    // Nothing to silence where it already rests.
    await introChoir.click();
    await expect(page.getByTestId("silence-here")).toHaveText("Choir rests here");
    await expect(page.getByTestId("silence-here")).toBeDisabled();
    await shot(page, "christmas-rests");

    // ---- silence the choir in the chorus: it has the tune → move it ---------
    await page.getByTestId(`cell-choir-${chorus}`).click();
    await expect(page.getByTestId("silence-here")).toHaveText("Silence choir here");
    await page.getByTestId("silence-here").click();
    const move = page.getByTestId("move-tune");
    await expect(move).toContainText("The choir has the tune in the chorus. Move it to:");
    await expect(page.getByTestId("move-tune-organ_church")).toHaveText("Organ (Church)");
    await expect(page.getByTestId("move-tune-string_section")).toBeVisible();
    await expect(page.getByTestId("move-tune-choir")).toHaveCount(0);
    await expect(page.getByTestId("move-tune-none")).toHaveText("Leave it out");
    await move.scrollIntoViewIfNeeded();
    await shot(page, "move-tune");
    // Cancel leaves the song alone.
    await page.getByTestId("move-tune-cancel").click();
    await expect(move).toHaveCount(0);
    await page.getByTestId("silence-here").click();
    gen = nextGenerate(page);
    await page.getByTestId("move-tune-organ_church").click();
    const r2 = await gen;
    const b2 = bodyOf(r2) as Body & { section_overrides?: Record<string, { instruments?: string[]; lead?: string }> };
    const mask = b2.section_overrides?.chorus?.instruments ?? [];
    expect(mask).not.toContain("choir");
    expect(mask).toContain("organ_church");
    expect(b2.section_overrides?.chorus?.lead).toBe("organ_church");
    await versionDone(page, 2);
    await expect(page.getByTestId(`cell-choir-${chorus}`)).toHaveText("rests");
    await expect(page.getByTestId(`cell-keys-${chorus}`)).toHaveText("on");
    await expect(page.getByTestId("silence-here")).toHaveText("Bring choir back here");
    // The render: the organ has the chorus tune, the choir sits it out.
    type Sec = { role: string; plays?: string[]; melody?: string | null; melody_default?: string | null };
    const res2 = (await (await page.request.get(`/api/jobs/${await jobOf(r2)}`)).json()) as { result: { sections: Sec[] } };
    for (const s of res2.result.sections.filter((x) => x.role === "chorus")) {
      expect(s.melody).toBe("organ_church");
      expect(s.melody_default).toBe("choir");
      expect(s.plays).toContain("organ_church");
      expect(s.plays).not.toContain("choir");
    }
    await shot(page, "choir-silenced");

    // ---- bring it back here: the tune goes back to the choir ---------------
    gen = nextGenerate(page);
    await page.getByTestId("silence-here").click();
    const b3 = bodyOf(await gen) as Body & { section_overrides?: Record<string, { lead?: string }> };
    expect(b3.section_overrides?.chorus?.lead).toBeUndefined();
    expect(b3.section_overrides?.chorus?.instruments).toBeUndefined();
    await versionDone(page, 3);
    await expect(page.getByTestId(`cell-choir-${chorus}`)).toHaveText("on");

    // ---- remove the choir from the whole song: move its tune too ----------
    await page.getByTestId("lane-name-choir").click();
    await expect(page.getByTestId("lane-panel")).toContainText("Choir · whole song");
    await page.getByTestId("lane-remove").click();
    await expect(page.getByTestId("move-tune")).toContainText("The choir has the tune in the chorus and outro");
    await expect(page.getByTestId("move-tune-none")).toHaveText("Let the band choose");
    gen = nextGenerate(page);
    await page.getByTestId("move-tune-organ_church").click();
    const b4 = bodyOf(await gen) as Body & { section_overrides?: Record<string, { lead?: string }> };
    expect(b4.instruments).not.toContain("choir");
    expect(b4.instruments).toContain("organ_church");
    expect(b4.section_overrides?.chorus?.lead).toBe("organ_church");
    expect(b4.section_overrides?.outro?.lead).toBe("organ_church");
    await versionDone(page, 4);
    await expect(choir).toHaveClass(/muted/);
    await expect(choir.locator(".ws-cell:not(.off)")).toHaveCount(0);
    await page.getByTestId("lane-name-choir").click();
    await expect(page.getByTestId("lane-restore")).toHaveText("Bring choir back");
    gen = nextGenerate(page);
    await page.getByTestId("lane-restore").click();
    const b5 = bodyOf(await gen) as Body & { section_overrides?: Record<string, { lead?: string }> };
    expect(b5.instruments).toContain("choir");
    expect(Object.values(b5.section_overrides ?? {}).filter((o) => o.lead)).toEqual([]);
    await versionDone(page, 5);
    await expect(choir).not.toHaveClass(/muted/);
  } finally {
    await deleteSessions(page.request, [await currentSessionId(page)]);
  }
});
