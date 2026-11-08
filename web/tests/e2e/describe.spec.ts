import { test, expect } from "@playwright/test";

/**
 * Describe → plan → revise → regenerate on the Generate screen. Works with
 * whichever interpreter answers (Claude via the queue, the local AI, or the
 * rules): it checks the plan landed on the form, that feedback changed the
 * plan, and that the regenerated song carries the plan's engine options
 * (arrangement, loudness) all the way through /api/generate.
 * Screenshots land in test-screenshots/.
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

test("describe a song, revise it in plain English, regenerate", async ({ page }) => {
  test.setTimeout(420_000);
  await page.goto("/app/");
  await tab(page, /Generate/);

  await page.getByTestId("describe-input").fill(
    "a funk fusion background bed for a product video, simple bass, no stabs, 120 bpm");
  await page.getByTestId("describe-fill").click();

  const report = page.getByTestId("describe-report");
  await expect(report).toBeVisible({ timeout: 240_000 });
  await expect(report).toContainText("Funk Fusion");
  await expect(report).toContainText("simple_bass");
  await expect(report).toContainText("No stabs");
  await expect(page.getByTestId("describe-interpreter")).toContainText(/Claude|local AI|rules/);
  await page.screenshot({ path: "test-screenshots/describe-plan.png", fullPage: true });

  // Feedback → revise → the form regenerates with the revised plan.
  const genReq = page.waitForRequest((r) => r.url().endsWith("/api/generate") && r.method() === "POST",
    { timeout: 240_000 });
  await page.getByTestId("revise-input").fill("too many fills");
  await page.getByTestId("revise-go").click();
  const body = JSON.parse((await genReq).postData() || "{}");
  expect(body.genre).toBe("funk_fusion_full");
  expect(body.tempo).toBe(120);
  expect(body.arrangement).toContain("pocket_drums");
  expect(body.arrangement).toContain("simple_bass");
  expect(body.hits).toEqual([]);
  expect(body.target_lufs).toBeLessThanOrEqual(-20);
  await expect(report).toContainText("pocket_drums");
  await page.screenshot({ path: "test-screenshots/describe-revised.png", fullPage: true });

  // The job finishes at the plan's loudness.
  const jobId = (await (await genReq).response())!.json().then((j: { job_id: string }) => j.job_id);
  const id = await jobId;
  let job: { status: string; result?: { loudness_lufs?: number }; error?: string } = { status: "" };
  await expect(async () => {
    job = await (await page.request.get(`/api/jobs/${id}`)).json();
    expect(["done", "error"]).toContain(job.status);
  }).toPass({ timeout: 300_000, intervals: [2000] });
  expect(job.error ?? null).toBeNull();
  expect(Math.abs((job.result?.loudness_lufs ?? 0) - body.target_lufs)).toBeLessThan(1);
});
