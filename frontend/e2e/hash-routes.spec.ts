import { expect, test } from "@playwright/test";

/*
 * Bookmarks and hand-typed URLs commonly carry a leading slash (#/solve).
 * These must resolve exactly like the canonical slash-less routes instead of
 * leaving an empty workspace shell under a fallback "Today" masthead.
 */

test("#/brain renders the Brain view like #brain", async ({ page }) => {
  await page.goto("/#/brain");
  await expect(page.locator(".context-title strong")).toHaveText("Brain");
  await expect(page.locator(".insight-card h2").first()).toBeVisible();
});

test("#/solve continues the scheduled session like bare #solve", async ({ page }) => {
  await page.goto("/#/solve");
  await expect(page).toHaveURL(/#solve\/ps-/);
  await expect(page.locator(".origin-chip")).toHaveText("Scheduled assignment");
});

test("canonical slash-less routes are unchanged", async ({ page }) => {
  await page.goto("/#brain");
  await expect(page.locator(".context-title strong")).toHaveText("Brain");
  await page.goto("/#library");
  await expect(page.locator(".context-title strong")).toHaveText("Library");
});
