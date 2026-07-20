import { expect, test } from "@playwright/test";

async function collectConsoleErrors(page: import("@playwright/test").Page) {
  const errors: string[] = [];
  page.on("console", message => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", error => errors.push(error.message));
  return errors;
}

test("scalable cockpit exposes bounded queue, review inbox, library, and problem-scoped lesson", async ({ page }) => {
  const errors = await collectConsoleErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Critical Connections in a Network" })).toBeVisible();
  await expect(page.getByText(/58 problems/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Visual Lab" })).toHaveCount(0);

  await page.getByRole("button", { name: "Queue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "The queue, without the pile-up." })).toBeVisible();
  await expect(page.locator(".problem-row")).toHaveCount(25);
  await expect(page.getByText(/maximum 25 rendered/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Redundant Connection/ })).toBeVisible();

  await page.getByLabel("Search problems").fill("Coin Change");
  await expect(page.getByRole("button", { name: /Coin Change/ })).toBeVisible();
  await expect(page.locator(".problem-row")).toHaveCount(1);

  await page.getByRole("button", { name: /Problems/, exact: true }).click();
  await expect(page.getByRole("heading", { name: "Every problem has its own history." })).toBeVisible();
  await page.getByLabel("Search problems").fill("Critical Connections");
  await page.getByRole("button", { name: /Critical Connections in a Network/ }).click();
  await expect(page.getByRole("heading", { name: "Critical Connections in a Network" })).toBeVisible();
  await expect(page.getByText("2 attempts")).toBeVisible();
  await page.getByRole("button", { name: /Lesson · available/ }).click();
  await expect(page.getByRole("img", { name: /low-link DFS graph/i })).toBeVisible();
  await page.getByRole("button", { name: "Next event" }).click();
  await page.getByRole("button", { name: "Next event" }).click();
  await expect(page.getByText(/Edge 0–1 becomes a DFS-tree edge/)).toBeVisible();

  await page.getByRole("button", { name: "Reviews", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Reviews ordered by evidence." })).toBeVisible();
  await expect(page.getByRole("button", { name: /Critical Connections in a Network/ })).toBeVisible();

  await page.getByRole("button", { name: "Profile" }).click();
  await expect(page.getByRole("heading", { name: /permiakoff/i })).toBeVisible();
  await expect(page.getByText("371", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("solve room previews hint and autosave behavior without mutating live evidence", async ({ page }) => {
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
  await expect(page.getByRole("heading", { name: "Critical Connections in a Network" })).toBeVisible();
  await page.getByRole("button", { name: /Reveal through H1/ }).click();
  await expect(page.getByText(/Can one DFS summarize/)).toBeVisible();
  const note = `Scale-safe autosave probe ${Date.now()}`;
  await page.getByLabel("Solution notes").fill(note);
  await expect(page.getByText(/^saved$/i)).toBeVisible();
  expect(noteRequests).toBe(1);
  expect(errors).toEqual([]);
});
