import { expect, test } from "@playwright/test";

test("training cockpit renders all primary views without console errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Critical Connections");
  await page.getByRole("button", { name: "Evidence", exact: true }).click();
  await expect(page.getByRole("heading", { name: /Memory, without/i })).toBeVisible();
  await page.getByRole("button", { name: "Visual Lab" }).click();
  await expect(page.getByRole("img", { name: /low-link DFS graph/i })).toBeVisible();
  await page.getByRole("button", { name: "Next event" }).click();
  await page.getByRole("button", { name: "Next event" }).click();
  await expect(page.getByText("Edge 0–1 becomes a DFS-tree edge.")).toBeVisible();
  await page.getByRole("button", { name: "Profile" }).click();
  await expect(page.getByText("371", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("solve room reveals hints progressively and saves notes", async ({ page }) => {
  await page.route("**/api/hints", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ level: "H1", highest_hint: "H1", text: "Can one DFS summarize whether a child subtree has an alternate route?" }),
  }));
  await page.route("**/api/assignments/*/notes", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ saved: true }),
  }));
  await page.goto("/#solve");
  await expect(page.getByText("Hidden until requested.").first()).toBeVisible();
  await page.getByRole("button", { name: "Reveal through H1" }).click();
  await expect(page.getByText(/Can one DFS summarize/i)).toBeVisible();
  const notes = page.getByRole("textbox", { name: "Solution notes" });
  await notes.fill("Parent-edge handling and strict bridge condition.");
  await page.waitForTimeout(800);
  await expect(page.getByText(/^saved$/i)).toBeVisible();
});

test("mobile has no document-level horizontal overflow", async ({ page }) => {
  await page.goto("/");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
