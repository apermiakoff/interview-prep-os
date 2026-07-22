import { expect, test, type Page } from "@playwright/test";

async function collectConsoleErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", message => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", error => errors.push(error.message));
  return errors;
}

/*
 * The e2e server serves a disposable copy of the live database, so the
 * scheduled assignment is whatever the learner actually has active. Tests
 * read it once and assert the invariant — scheduled work stays scheduled —
 * against that, never against a hardcoded title.
 */
async function scheduledAssignment(page: Page) {
  const bootstrap = await page.request.get("/api/bootstrap").then(r => r.json());
  expect(bootstrap.active_assignment).not.toBeNull();
  return bootstrap.active_assignment as { id: string; problem_id: number; title: string; assigned_on: string; hint_levels: string[] };
}

async function openHintDrawerIfCollapsed(page: Page) {
  const toggle = page.locator(".hint-drawer-toggle");
  if (await toggle.isVisible()) await toggle.click();
}

async function startAdHocFromLibrary(page: Page, title: string) {
  await page.goto("/#library");
  await page.getByLabel("Search problems").fill(title);
  const row = page.locator(".problem-row", { hasText: title }).first();
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Practice" }).click();
  await expect(page).toHaveURL(/#solve\/ps-/);
  await expect(page.locator(".bar-identity strong")).toContainText(title);
}

test("Today leads with the scheduled assignment", async ({ page }) => {
  const errors = await collectConsoleErrors(page);
  const scheduled = await scheduledAssignment(page);
  await page.goto("/");
  await expect(page.locator(".now-title")).toContainText(scheduled.title);
  await expect(page.locator(".now-panel .button.primary")).toBeVisible();
  await expect(page.getByText("Why this, from your evidence")).toBeVisible();
  await expect(page.getByText(/Deterministic selection · learner-policy/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("bootstrap exposes hint levels but never hint bodies", async ({ page }) => {
  const bootstrap = await page.request.get("/api/bootstrap").then(r => r.json());
  const active = bootstrap.active_assignment;
  expect(active).not.toBeNull();
  expect(active.hint_levels.length).toBeGreaterThan(0);
  expect(active).not.toHaveProperty("hints");
  expect(active).not.toHaveProperty("bujo");
});

test("Library offers Practice and external actions on every rendered row", async ({ page }) => {
  const errors = await collectConsoleErrors(page);
  await page.goto("/#library");
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await expect(page.locator(".problem-row")).toHaveCount(25);
  await expect(page.locator(".problem-row .practice-button")).toHaveCount(25);
  await expect(page.locator(".problem-row .external-button")).toHaveCount(25);
  await expect(page.getByText(/maximum 25 rendered/)).toBeVisible();
  await expect(page.getByPlaceholder("Search title, #, or slug")).toBeVisible();

  // Search by LeetCode number reaches the same problem as its title.
  await page.getByLabel("Search problems").fill("1192");
  await expect(page.locator(".problem-row")).toHaveCount(1);
  await expect(page.locator(".problem-row").first()).toContainText("Critical Connections in a Network");

  await page.getByLabel("Search problems").fill("");
  await page.getByLabel("Track filter").selectOption("outtalent");
  await expect(page.getByText(/of 40/)).toBeVisible();

  // Bulk refresh keeps the track filter applied (regression check).
  await page.getByRole("button", { name: "Queue", exact: true }).click();
  await expect(page.getByRole("button", { name: "Queue", exact: true })).toHaveAttribute("aria-current", "page");
  await page.getByRole("button", { name: "Reviews", exact: true }).click();
  await expect(page.getByRole("button", { name: "Reviews", exact: true })).toHaveAttribute("aria-current", "page");
  expect(errors).toEqual([]);
});

test("ad hoc practice: Library → Practice → paper-first solve → recorded evidence, scheduled work untouched", async ({ page, viewport }) => {
  const errors = await collectConsoleErrors(page);
  const scheduled = await scheduledAssignment(page);
  const target = (viewport?.width ?? 1366) < 500 ? "Rotting Oranges" : "Walls and Gates";
  expect(scheduled.title).not.toBe(target);
  await startAdHocFromLibrary(page, target);

  // Paper-first: extra practice framing, no scratchpad, no autosave chatter.
  await expect(page.locator(".origin-chip")).toHaveText("Extra practice");
  await expect(page.locator(".extra-practice-note")).toContainText(scheduled.title);
  await expect(page.locator(".extra-practice-note")).toContainText("remains scheduled for");
  await expect(page.getByText("Read on LeetCode. Reason on paper. Implement there.")).toBeVisible();
  await expect(page.locator("textarea")).toHaveCount(0);
  await expect(page.getByText(/autosave|saved/i)).toHaveCount(0);
  await expect(page.locator(".leetcode-cta")).toBeVisible();

  // Hints unlock strictly in order, and the first reveal asks for confirmation.
  await openHintDrawerIfCollapsed(page);
  await expect(page.locator(".rail-state")).toContainText("H0 · independent");
  await expect(page.getByRole("button", { name: "Reveal H2" })).toHaveCount(0);
  await expect(page.locator(".hint-step.locked")).toHaveCount(3);
  await page.getByRole("button", { name: "Reveal H1", exact: true }).click();
  await expect(page.getByText(/records this attempt as assisted/)).toBeVisible();
  await page.getByRole("button", { name: /Reveal H1 — record assisted/ }).click();
  await expect(page.locator(".hint-step.revealed p")).toContainText(/Recognition/);
  await expect(page.getByRole("button", { name: "Reveal H2", exact: true })).toBeVisible();
  await expect(page.locator(".rail-state")).toContainText("Used through H1");

  // Finish: outcome first; independence is derived, not a checkbox.
  await page.getByRole("button", { name: "Finish attempt" }).click();
  await expect(page.getByRole("radio", { name: /Independent/ })).toBeDisabled();
  const record = page.getByRole("button", { name: "Record attempt" });
  await expect(record).toBeDisabled();
  await page.getByRole("radio", { name: /Assisted \/ slow/ }).click();
  await expect(record).toBeDisabled(); // blocker required for yellow
  await page.getByLabel(/Primary blocker/).selectOption("implementation");
  await expect(page.getByTestId("finish-preview")).toContainText("yellow · assisted · H1");
  await expect(page.getByTestId("finish-preview")).toContainText("blocker: implementation");
  await record.click();

  // Evidence lands on the practiced problem…
  await expect(page).toHaveURL(/#problem\/\d+/);
  await page.getByRole("button", { name: "History", exact: true }).click();
  await expect(page.locator(".attempt-line").first()).toContainText("yellow");

  // …and the scheduled assignment is still today's work, byte-for-byte.
  const after = await scheduledAssignment(page);
  expect(after.id).toBe(scheduled.id);
  expect(after.assigned_on).toBe(scheduled.assigned_on);
  await page.goto("/");
  await expect(page.locator(".now-title")).toContainText(scheduled.title);
  expect(errors).toEqual([]);
});

test("bare #solve continues the scheduled session", async ({ page }) => {
  const scheduled = await scheduledAssignment(page);
  await page.goto("/#solve");
  await expect(page).toHaveURL(/#solve\/ps-/);
  await expect(page.locator(".origin-chip")).toHaveText("Scheduled assignment");
  await expect(page.locator(".bar-identity strong")).toContainText(scheduled.title);
});

test("ambiguous finish retries one event id and uses the canonical duplicate response", async ({ page }) => {
  const listing = await page.request.get("/api/problems?search=accounts+merge").then(r => r.json());
  const envelope = await page.request
    .post(`/api/problems/${listing.items[0].id}/practice-sessions`, { data: {} })
    .then(r => r.json());
  const sessionId = envelope.session.id as string;
  await page.goto(`/#solve/${sessionId}`);

  // Freeze a duration above the API maximum; the sheet must disclose the cap.
  await page.evaluate(id => {
    sessionStorage.setItem(`solve-timer:${id}`, JSON.stringify({
      elapsed: 361 * 60,
      running: false,
      updatedAt: Date.now(),
    }));
  }, sessionId);
  await page.reload();

  const finish = page.getByRole("button", { name: "Finish attempt" });
  await finish.click();
  await expect(page.getByRole("button", { name: "Close without recording" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(finish).toBeFocused();
  await finish.click();
  await page.getByRole("radio", { name: /Skipped/ }).click();
  await expect(page.getByTestId("finish-preview")).toContainText("360 min");
  await expect(page.getByTestId("finish-preview")).toContainText("duration capped");

  const ids: string[] = [];
  let first = true;
  await page.route(`**/api/practice-sessions/${sessionId}/attempts`, async route => {
    ids.push(route.request().postDataJSON().event_id);
    if (first) {
      first = false;
      await route.fetch(); // server commits, but the browser loses the response
      await route.abort("failed");
      return;
    }
    await route.continue();
  });

  const record = page.getByRole("button", { name: "Record attempt" });
  await record.click();
  await expect(page.locator(".finish-sheet .form-message")).toBeVisible();
  await record.click();
  await expect(page).toHaveURL(/#problem\/\d+/);
  expect(ids).toHaveLength(2);
  expect(ids[1]).toBe(ids[0]);
});

test("same-problem extra practice says the scheduled assignment is preserved", async ({ page }) => {
  const scheduled = await scheduledAssignment(page);
  await page.goto("/#library");
  await page.getByLabel("Search problems").fill(scheduled.title);
  const row = page.locator(".problem-row", { hasText: scheduled.title }).first();
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Practice", exact: true }).click();
  await expect(page).toHaveURL(/#solve\/ps-/);
  await expect(page.locator(".origin-chip")).toHaveText("Extra practice");
  await expect(page.locator(".extra-practice-note")).toContainText(
    "This problem's scheduled assignment remains scheduled",
  );
  const after = await scheduledAssignment(page);
  expect(after.id).toBe(scheduled.id);
});

test("random practice starts an ad hoc session from the filtered set", async ({ page }) => {
  await page.goto("/#library");
  await expect(page.locator(".problem-row").first()).toBeVisible();
  await page.getByRole("button", { name: /Random practice/ }).click();
  await expect(page).toHaveURL(/#solve\/ps-/, { timeout: 15_000 });
  await expect(page.locator(".origin-chip")).toHaveText("Extra practice");
});

test("timer persists elapsed seconds across a reload without auto-submitting", async ({ page }) => {
  const listing = await page.request.get("/api/problems?search=accounts+merge").then(r => r.json());
  const problemId = listing.items[0].id;
  const envelope = await page.request
    .post(`/api/problems/${problemId}/practice-sessions`, { data: {} })
    .then(r => r.json());
  await page.goto(`/#solve/${envelope.session.id}`);
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await expect(page.locator(".timer-phase")).toHaveText("live");
  await page.waitForTimeout(1600);
  await page.reload();
  await expect(page.locator(".timer-phase")).toHaveText("live");
  const clock = await page.locator(".timer-clock").textContent();
  expect(clock).not.toBe("35:00");
});

test("problem details always offer a paper attempt and honest content labels", async ({ page }) => {
  // The scheduled problem's detail routes into its scheduled session.
  const scheduled = await scheduledAssignment(page);
  await page.goto(`/#problem/${scheduled.problem_id}`);
  await expect(page.getByRole("heading", { name: scheduled.title })).toBeVisible();
  await expect(page.getByRole("button", { name: /Continue scheduled attempt/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /extra practice/i })).toBeVisible();
  await expect(page.getByText(/scheduled assignment remains untouched/)).toBeVisible();

  // The curated low-link problem keeps its curated labels.
  await page.goto("/#library");
  await page.getByLabel("Search problems").fill("1192");
  await page.locator(".problem-row .problem-identity").first().click();
  await expect(page.getByRole("heading", { name: "Critical Connections in a Network" })).toBeVisible();
  await expect(page.getByRole("button", { name: /paper attempt/ })).toBeVisible();
  await page.locator(".problem-inspector summary").click();
  await expect(page.getByText("Curated low-link lesson")).toBeVisible();
  await expect(page.getByText("Curated hint ladder")).toBeVisible();

  // Any other problem offers an ad hoc paper attempt with generated provenance stated.
  await page.goto("/#library");
  await page.getByLabel("Search problems").fill("Coin Change");
  await page.locator(".problem-row", { hasText: /^Coin Change/ }).first().locator(".problem-identity").click();
  await expect(page.getByRole("heading", { name: "Coin Change" })).toBeVisible();
  await expect(page.getByRole("button", { name: /paper attempt/ })).toBeVisible();
  await page.locator(".problem-inspector summary").click();
  await expect(page.getByText("Generated practice scaffold")).toBeVisible();
  await expect(page.getByText("Generated hint ladder")).toBeVisible();

  // The lazy lesson is a staged scaffold that names its generator.
  await page.getByRole("button", { name: "Lesson", exact: true }).click();
  await expect(page.getByText(/deterministic-skill-scaffold\/1.0/)).toBeVisible();
  for (const stage of ["Understand", "Derive", "Implement", "Test", "Reflect"]) {
    await expect(page.locator(".scaffold-stage h3", { hasText: stage })).toBeVisible();
  }
  await expect(page.getByText(/not an authored walkthrough/)).toBeVisible();
});

test("both themes render the cockpit coherently", async ({ page }) => {
  const listing = await page.request.get("/api/problems?search=course+schedule").then(r => r.json());
  const envelope = await page.request
    .post(`/api/problems/${listing.items[0].id}/practice-sessions`, { data: {} })
    .then(r => r.json());
  await page.goto(`/#solve/${envelope.session.id}`);
  await expect(page.locator(".session-bar")).toBeVisible();
  const ink = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await page.locator(".theme-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  // The background animates over ~350ms; poll past the transition.
  await expect
    .poll(() => page.evaluate(() => getComputedStyle(document.body).backgroundColor))
    .not.toBe(ink);
  await expect(page.locator(".bar-identity strong")).toBeVisible();
  await expect(page.getByRole("button", { name: "Finish attempt" })).toBeVisible();
});

test("Brain ranks diagnoses with honest confidence and keeps the ledger secondary", async ({ page }) => {
  const errors = await collectConsoleErrors(page);
  await page.goto("/#brain");
  await expect(page.getByRole("heading", { name: "What is actually breaking, with receipts." })).toBeVisible();
  const insights = page.locator(".insight-card");
  await expect(insights.first()).toBeVisible();
  expect(await insights.count()).toBeLessThanOrEqual(3);
  await expect(page.locator(".insight-card .chip").first()).toContainText(/recurring|suspected/);
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
  const trackTitles = await page.locator(".track-header h2").allTextContents();
  expect(trackTitles[0]).toContain("Outtalent");
  expect(trackTitles[1]).toContain("Deep supplemental");
  await expect(page.locator(".track-line.non-problem .status-pill").first()).toBeVisible();
  await expect(page.getByText(/Curriculum provenance:/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("legacy hash routes redirect into the new IA", async ({ page }) => {
  await page.goto("/#evidence");
  await expect(page.getByRole("heading", { name: "What is actually breaking, with receipts." })).toBeVisible();
  await page.goto("/#queue");
  await expect(page.getByRole("button", { name: "Queue", exact: true })).toHaveAttribute("aria-current", "page");
});

test("SPA navigation moves focus to the new main view", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".now-title")).toBeVisible();
  await page.getByRole("button", { name: /^Library/ }).click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await expect(page.locator("#main-content")).toBeFocused();
  await expect(page.locator("#main-content")).toHaveAttribute("tabindex", "-1");
});
