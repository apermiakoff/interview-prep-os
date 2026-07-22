import { expect, test, type Page, type Route } from "@playwright/test";

const ready = { status: "ready", enabled: true, provider: "ollama", model: "test-model", base_url: "http://ollama:11434" };
const run = (id: string, kind: string) => ({ id, kind, scope: kind === "diagnosis" ? "learning" : "problem", scope_id: kind === "diagnosis" ? "learner" : "1", status: "completed", attempts: 1, max_attempts: 2, created_at: "2026-01-01", updated_at: "2026-01-01", completed_at: "2026-01-01" });
const fulfill = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
async function noOverflow(page: Page) { expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1); }

test("AI-disabled real status links to setup guidance", async ({ page }) => {
  await page.goto("/#settings/ai");
  await expect(page.getByRole("heading", { name: "Community AI setup" })).toBeVisible();
  await expect(page.getByText("Community AI is disabled.")).toBeVisible();
  await expect(page.getByText(/docker compose --profile ai up -d/)).toBeVisible();
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await noOverflow(page);
});

test("session coach completes durable mocked flow and restores close focus", async ({ page }) => {
  const listing = await page.request.get("/api/problems?search=accounts+merge").then(response => response.json());
  const envelope = await page.request.post(`/api/problems/${listing.items[0].id}/practice-sessions`, { data: {} }).then(response => response.json());
  const conversation = { id: "c-e2e", scope: "session", scope_id: envelope.session.id, title: "Solve-room coach", created_at: "2026-01-01", updated_at: "2026-01-01" };
  let created = false, answered = false;
  await page.route("**/api/ai/**", route => {
    const url = new URL(route.request().url()); const method = route.request().method();
    if (url.pathname.endsWith("/status")) return fulfill(route, ready);
    if (url.pathname.endsWith("/conversations") && method === "GET") return fulfill(route, created ? [conversation] : []);
    if (url.pathname.endsWith("/conversations") && method === "POST") { created = true; return fulfill(route, conversation, 201); }
    if (url.pathname.endsWith("/messages")) { answered = true; return fulfill(route, { run: { ...run("chat-run", "chat"), scope: "session", scope_id: envelope.session.id, conversation_id: conversation.id }, created: true }, 202); }
    if (url.pathname.endsWith("/runs/chat-run")) return fulfill(route, { ...run("chat-run", "chat"), scope: "session", scope_id: envelope.session.id });
    if (url.pathname.endsWith("/conversations/c-e2e")) return fulfill(route, { ...conversation, messages: answered ? [{ id: "a1", role: "assistant", content: "What invariant survives each step?", created_at: "2026-01-01" }] : [] });
    return fulfill(route, { detail: `unmocked ${url.pathname}` }, 404);
  });
  await page.goto(`/#solve/${envelope.session.id}`); const trigger = page.getByRole("button", { name: "Coach" }); await trigger.click();
  const isMobile = (page.viewportSize()?.width || 0) <= 700;
  if (isMobile) {
    const dialog = page.getByRole("dialog", { name: "Session AI coach" });
    await expect(dialog).toBeVisible();
    await expect(page.getByRole("button", { name: "Close coach" })).toBeFocused();
    await expect(page.locator(".app-shell")).toHaveAttribute("inert", "");
    expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");
    await page.keyboard.press("Shift+Tab");
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest('.coach-overlay')))).toBe(true);
  } else {
    await expect(page.getByRole("complementary", { name: "Session AI coach" })).toBeVisible();
    await expect(page.locator(".app-shell")).not.toHaveAttribute("inert", "");
    expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
  }
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
  await trigger.click();
  await expect(page.getByText(/AI-assisted and non-independent/)).toBeVisible();
  await page.getByLabel("Your reasoning or question").fill("I lose track of state"); await page.getByRole("button", { name: "Ask coach" }).click();
  await expect(page.getByText("What invariant survives each step?")).toBeVisible();
  await page.getByRole("button", { name: "Close coach" }).click(); await expect(trigger).toBeFocused();
  if (isMobile) { await expect(page.locator(".app-shell")).not.toHaveAttribute("inert", ""); expect(await page.evaluate(() => document.body.style.overflow)).toBe(""); }
  await noOverflow(page);
});

test("problem AI is locked to the exact open solve session", async ({ page }) => {
  const listing = await page.request.get("/api/problems?search=accounts+merge").then(response => response.json());
  const id = listing.items[0].id;
  const envelope = await page.request.post(`/api/problems/${id}/practice-sessions`, { data: {} }).then(response => response.json());
  await page.goto(`/#problem/${id}`);
  await expect(page.getByRole("heading", { name: /Problem AI is locked/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "coach", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Generated lesson" })).toHaveCount(0);
  await page.getByRole("button", { name: /Use session Coach/ }).click();
  await expect(page).toHaveURL(new RegExp(`#solve/${envelope.session.id}$`));
  await expect(page.getByRole("button", { name: "Coach" })).toBeVisible();
});

test("accepted session AI stays assisted when run polling fails", async ({ page }) => {
  const listing = await page.request.get("/api/problems?search=accounts+merge").then(response => response.json());
  const envelope = await page.request.post(`/api/problems/${listing.items[0].id}/practice-sessions`, { data: {} }).then(response => response.json());
  const conversation = { id: "c-fail", scope: "session", scope_id: envelope.session.id, title: "Solve-room coach", created_at: "2026-01-01", updated_at: "2026-01-01" };
  await page.route("**/api/ai/**", route => {
    const url = new URL(route.request().url()); const method = route.request().method();
    if (url.pathname.endsWith("/status")) return fulfill(route, ready);
    if (url.pathname.endsWith("/conversations") && method === "GET") return fulfill(route, []);
    if (url.pathname.endsWith("/conversations") && method === "POST") return fulfill(route, conversation, 201);
    if (url.pathname.endsWith("/messages")) return fulfill(route, { run: { ...run("poll-fail", "chat"), status: "queued", scope: "session", scope_id: envelope.session.id, conversation_id: conversation.id }, created: true }, 202);
    if (url.pathname.endsWith("/runs/poll-fail")) return fulfill(route, { detail: "poll unavailable" }, 500);
    return fulfill(route, { detail: "unmocked" }, 404);
  });
  await page.goto(`/#solve/${envelope.session.id}`);
  await page.getByRole("button", { name: "Coach" }).click();
  await page.getByLabel("Your reasoning or question").fill("Coach me once");
  await page.getByRole("button", { name: "Ask coach" }).click();
  await expect(page.getByRole("alert")).toContainText("poll unavailable");
  await page.getByRole("button", { name: "Close coach" }).click();
  await page.getByRole("button", { name: "Finish attempt" }).click();
  await expect(page.getByRole("radio", { name: /Independent/ })).toBeDisabled();
  await expect(page.getByText(/AI coaching used — this attempt records as assisted/)).toBeVisible();
  await page.getByRole("button", { name: "Close without recording" }).click();
});

test("problem AI lesson generation and safe semantic visualization render", async ({ page }) => {
  const listing = await page.request.get("/api/problems?search=coin+change").then(response => response.json()); const id = listing.items[0].id;
  let generated = false;
  const lesson = { id: "lesson-a", scope: "problem", scope_id: String(id), kind: "lesson", version: 1, schema_version: "lesson@1", run_id: "lesson-run", context_snapshot_id: "snap", prompt_version: "p1", provider: "ollama", model: "test-model", created_at: "2026-01-01", content: { schema_version: "lesson@1", objectives: ["Derive the recurrence"], recognition_signals: ["Overlapping subproblems"], sections: [{ heading: "Invariant", body: "Each cell is the best known prefix result." }], complexity: { time: "O(n)", space: "O(n)" }, failures: ["Greedy choice"], provenance_notes: [] } };
  const viz = { id: "viz-a", scope: "problem", scope_id: String(id), kind: "visualization", version: 1, schema_version: "visualization@1", run_id: "viz-run", context_snapshot_id: "snap", prompt_version: "p1", provider: "ollama", model: "test-model", created_at: "2026-01-01", content: { schema_version: "visualization@1", renderer: "array-trace@1", title: "DP trace", entities: [{ id: "c0", label: "dp[0]", kind: "cell", data: { value: 0 } }], events: [{ op: "visit", targets: ["c0"], note: "Base case" }] } };
  await page.route("**/api/ai/**", route => { const url = new URL(route.request().url()); const method = route.request().method(); if (url.pathname.endsWith("/status")) return fulfill(route, ready); if (url.pathname.endsWith("/lesson") && method === "POST") { generated = true; return fulfill(route, { run: run("lesson-run", "lesson"), created: true }, 202); } if (url.pathname.endsWith("/runs/lesson-run")) return fulfill(route, run("lesson-run", "lesson")); if (url.pathname.endsWith("/artifacts") && url.searchParams.get("kind") === "lesson") return fulfill(route, generated ? [lesson] : []); if (url.pathname.endsWith("/artifacts") && url.searchParams.get("kind") === "visualization") return fulfill(route, [viz]); return fulfill(route, { detail: "unmocked" }, 404); });
  await page.goto(`/#problem/${id}`); await page.getByRole("button", { name: "Generated lesson" }).click(); await page.getByPlaceholder("Emphasize recognition signals").fill("Focus on recurrence"); await page.getByRole("button", { name: "Generate", exact: true }).click(); await expect(page.getByText("Derive the recurrence")).toBeVisible();
  await page.getByRole("button", { name: "Visualization", exact: true }).click(); await expect(page.getByRole("heading", { name: "DP trace" })).toBeVisible(); await expect(page.getByText("dp[0]")).toBeVisible(); expect(await page.locator("script", { hasText: "DP trace" }).count()).toBe(0); await noOverflow(page);
});

test("Brain renders mocked diagnosis as explicitly unconfirmed", async ({ page }) => {
  let generated = false; const artifact = { id: "d1", scope: "learning", scope_id: "learner", kind: "diagnosis", version: 1, schema_version: "diagnosis@1", run_id: "d-run", context_snapshot_id: "s", prompt_version: "p", provider: "ollama", model: "test-model", created_at: "2026-01-01", content: { schema_version: "diagnosis@1", observations: ["Two implementation blockers recorded"], hypotheses: [{ type: "learning_bottleneck", status: "candidate", statement: "May code before stating the invariant", confidence: .45, evidence: [{ id: "attempt:1", quote: "implementation" }] }], interventions: [{ action: "State the invariant before coding", rationale: "Test this candidate", requires_user_action: true }] } };
  await page.route("**/api/ai/**", route => { const url = new URL(route.request().url()); const method = route.request().method(); if (url.pathname.endsWith("/status")) return fulfill(route, ready); if (url.pathname.endsWith("/diagnosis/history")) return fulfill(route, generated ? [artifact] : []); if (url.pathname.endsWith("/learning/diagnosis") && method === "POST") { generated = true; return fulfill(route, { run: run("d-run", "diagnosis"), created: true }, 202); } if (url.pathname.endsWith("/runs/d-run")) return fulfill(route, run("d-run", "diagnosis")); return fulfill(route, { detail: "unmocked" }, 404); });
  await page.goto("/#brain"); await page.getByRole("button", { name: "Generate diagnosis" }).click(); await expect(page.getByText(/candidate · 45% confidence · unconfirmed/)).toBeVisible(); await expect(page.getByText("User action required")).toBeVisible(); await noOverflow(page);
});
