import { test, expect, type Page } from "@playwright/test";
import { openCreateMode, tab } from "./nav";

/**
 * A carol named in Describe really plays that carol: the plan's `tune` (and
 * `length_seconds`) reach POST /api/generate, from the Create session and
 * from the Advanced form. The generate call itself is stubbed (the body is
 * what's under test; rendering is covered by the Python tests), so nothing
 * is rendered or saved.
 */

const FAKE_JOB = "carol-describe-stub";

async function stubGenerate(page: Page): Promise<Record<string, unknown>[]> {
  const bodies: Record<string, unknown>[] = [];
  await page.route("**/api/generate", async (route) => {
    bodies.push(JSON.parse(route.request().postData() || "{}"));
    await route.fulfill({ json: { job_id: FAKE_JOB } });
  });
  await page.route(`**/api/jobs/${FAKE_JOB}**`, (route) =>
    route.fulfill({ json: { id: FAKE_JOB, status: "error", progress: 1, message: "", error: "stubbed in the test" } }));
  return bodies;
}

test("Describe: 'jazz trio Silent Night, background' sends tune silent_night to /api/generate", async ({ page }) => {
  test.setTimeout(300_000);
  const bodies = await stubGenerate(page);
  await page.goto("/app/");
  await page.evaluate(() => localStorage.removeItem("aimusic.create.session"));
  await page.reload();
  await tab(page, /Create/);
  await page.getByTestId("session-input").fill("jazz trio Silent Night, background, about 3 minutes");
  await page.getByTestId("session-input-send").click();
  await expect.poll(() => bodies.length, { timeout: 240_000 }).toBeGreaterThan(0);
  const b = bodies[0];
  expect(b.genre).toBe("christmas_jazz_trio_full");
  expect(b.tune).toBe("silent_night");
  expect(Number(b.length_seconds)).toBeGreaterThanOrEqual(150);
  await expect(page.getByTestId("msg-describe").getByTestId("plan-chips")).toContainText(/Silent Night/);
});

test("Advanced form keeps the plan's tune and length", async ({ page }) => {
  const bodies = await stubGenerate(page);
  await page.addInitScript(() => {
    if (sessionStorage.getItem("seeded")) return;
    sessionStorage.setItem("seeded", "1");
    localStorage.setItem("aimusic.create.session", JSON.stringify({
      title: "Carol", msgs: [{ id: "u1", role: "user", text: "Silent Night backing track in G" },
        { id: "a1", role: "app", kind: "describe", chips: ["Christmas"], version: 1 }],
      versions: [{ n: 1, status: "error", error: "Interrupted", progress: 0, message: "", jobId: null,
        plan: { genre: "christmas_orchestral_full", key: "G", tune: "silent_night", length_seconds: 200,
                arrangement: "backing_track" } }],
    }));
  });
  await page.goto("/app/");
  await expect(page.getByTestId("session-title")).toHaveText("Carol");
  await openCreateMode(page, "advanced");
  const adv = page.locator(".tab-pane:not(.hidden) .tab-pane:not(.hidden)");
  await expect(adv.locator(".keypick").first()).toContainText("G", { timeout: 15_000 });
  await adv.getByRole("button", { name: /Generate Song/ }).click();
  await expect.poll(() => bodies.length, { timeout: 30_000 }).toBeGreaterThan(0);
  expect(bodies[0].genre).toBe("christmas_orchestral_full");
  expect(bodies[0].tune).toBe("silent_night");
  expect(bodies[0].length_seconds).toBe(200);
  expect(bodies[0].arrangement).toBe("backing_track");
});
