import { expect, test, type Page } from "@playwright/test";

async function collectConsoleErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", message => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", error => errors.push(error.message));
  return errors;
}

test("Today leads with Now, Why, Risk, due count, and Next gate", async ({ page }) => {
  const errors = await collectConsoleErrors(page);
  await page.goto("/");
  await expect(page.locator(".now-title")).toBeVisible();
  await expect(page.locator(".now-panel .button.primary")).toBeVisible();
  await expect(page.getByText("Why this, from your evidence")).toBeVisible();
  await expect(page.locator(".why-list li").first()).toBeVisible();
  await expect(page.getByText("Risk", { exact: true })).toBeVisible();
  await expect(page.getByText(/below 85% retention/)).toBeVisible();
  await expect(page.getByText("Next gate", { exact: true })).toBeVisible();
  await expect(page.getByText(/Deterministic selection · learner-policy/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("Brain ranks diagnoses with honest confidence and keeps the ledger secondary", async ({ page }) => {
  const errors = await collectConsoleErrors(page);
  await page.goto("/#brain");
  await expect(page.getByRole("heading", { name: "What is actually breaking, with receipts." })).toBeVisible();
  const insights = page.locator(".insight-card");
  await expect(insights.first()).toBeVisible();
  expect(await insights.count()).toBeLessThanOrEqual(3);
  // Confidence language is explicit: recurring needs >= 2 observations.
  await expect(page.locator(".insight-card .chip").first()).toContainText(/recurring|suspected/);
  await expect(page.getByText(/only 1 observation/).first()).toBeVisible();
  // Raw ledger stays collapsed until requested.
  await expect(page.locator(".attempt-line")).toHaveCount(0);
  await page.getByRole("button", { name: /Show \d+ events/ }).click();
  await expect(page.locator(".attempt-line").first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("Roadmap shows six-dimension heatmap with honest states and ordered tracks", async ({ page }) => {
  const errors = await collectConsoleErrors(page);
  await page.goto("/#roadmap");
  const headers = page.locator(".heatmap thead th");
  await expect(headers).toHaveText(["Skill", "Recognize", "Derive", "Implement", "Test", "Explain", "Retain"]);
  // Cells carry state words and evidence counts, not invented percentages.
  await expect(page.locator(".heat-cell.fragile").first()).toBeVisible();
  await page.locator(".heat-cell.fragile").first().click();
  await expect(page.locator(".heatmap-detail")).toContainText(/fragile · \d+ obs/);
  await expect(page.locator(".heatmap-detail p")).not.toHaveText("");
  // Outtalent (formal) is listed before the deep supplemental track.
  const trackTitles = await page.locator(".track-header h2").allTextContents();
  expect(trackTitles[0]).toContain("Outtalent");
  expect(trackTitles[1]).toContain("Deep supplemental");
  // Non-problem rows are declared, not silently dropped or invented.
  await expect(page.locator(".track-line.non-problem .status-pill").first()).toBeVisible();
  await expect(page.getByText(/Curriculum provenance:/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("Library keeps bounded pagination, search, and track filters", async ({ page }) => {
  const errors = await collectConsoleErrors(page);
  await page.goto("/#library");
  await expect(page.getByRole("heading", { name: "Every problem, every track, one history." })).toBeVisible();
  await expect(page.locator(".problem-row")).toHaveCount(25);
  await expect(page.getByText(/maximum 25 rendered/)).toBeVisible();

  await page.getByLabel("Track filter").selectOption("outtalent");
  await expect(page.getByText(/of 40/)).toBeVisible();

  await page.getByLabel("Track filter").selectOption("");
  await page.getByLabel("Search problems").fill("Coin Change");
  await expect(page.getByRole("button", { name: /Coin Change/ })).toBeVisible();
  await expect(page.locator(".problem-row")).toHaveCount(1);

  // Queue and Reviews are Library subviews now.
  await page.getByRole("button", { name: "Queue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "The queue, without the pile-up." })).toBeVisible();
  await page.getByRole("button", { name: "Reviews", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Reviews ordered by evidence." })).toBeVisible();
  expect(errors).toEqual([]);
});

test("legacy hash routes redirect into the new IA", async ({ page }) => {
  await page.goto("/#evidence");
  await expect(page.getByRole("heading", { name: "What is actually breaking, with receipts." })).toBeVisible();
  await page.goto("/#queue");
  await expect(page.getByRole("heading", { name: "The queue, without the pile-up." })).toBeVisible();
});

test("problem workspace exposes skills, placements, related problems, and honest lesson state", async ({ page }) => {
  const errors = await collectConsoleErrors(page);
  await page.goto("/#library");
  await page.getByLabel("Search problems").fill("Coin Change");
  await page.getByRole("button", { name: /Coin Change/ }).click();
  await expect(page.getByRole("heading", { name: "Coin Change" })).toBeVisible();
  await expect(page.getByText("Skills this problem trains")).toBeVisible();
  await expect(page.locator(".skill-chip").first()).toBeVisible();
  await expect(page.locator(".placement-chips > span").first()).toContainText("Outtalent");
  await expect(page.getByText("Related through shared skills")).toBeVisible();
  // Lesson honesty: no fabricated deep lesson for this problem.
  await page.getByRole("button", { name: /^Lesson$/ }).click();
  await expect(page.getByText(/No authored lesson yet — nothing is auto-generated/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("solve room reveals hints on request and autosaves notes without mutating evidence", async ({ page }) => {
  const errors = await collectConsoleErrors(page);
  let noteRequests = 0;
  await page.route("**/api/hints", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ level: "H1", highest_hint: "H1", text: "Can one DFS summarize an alternate route from every subtree?" }),
  }));
  await page.route("**/api/assignments/*/notes", route => {
    noteRequests += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, updated_at: new Date().toISOString() }),
    });
  });
  await page.goto("/#solve");
  await expect(page.locator(".hint-item p").first()).toContainText("Hidden until requested.");
  await page.getByRole("button", { name: /Reveal through H1/ }).click();
  await expect(page.getByText(/Can one DFS summarize/)).toBeVisible();
  // Copy matches the recorded policy: any hint => assisted.
  await expect(page.getByText(/any revealed hint records this attempt as assisted/i)).toBeVisible();
  await expect(page.getByText(/Independent implementation \(off: hints used\)/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Solved \(records assisted\)/ })).toBeVisible();
  const note = `Scale-safe autosave probe ${Date.now()}`;
  await page.getByLabel("Solution notes").fill(note);
  await expect(page.getByText(/^saved$/i)).toBeVisible();
  expect(noteRequests).toBe(1);
  expect(errors).toEqual([]);
});
