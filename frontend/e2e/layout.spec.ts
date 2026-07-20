import { expect, test, type Locator, type Page } from "@playwright/test";

async function bottomEdge(locator: Locator) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return box!.y + box!.height;
}

async function fontSizeOf(locator: Locator) {
  return locator.evaluate(element => parseFloat(getComputedStyle(element).fontSize));
}

test.describe("desktop 1366x768", () => {
  test.skip(({ viewport }) => (viewport?.width ?? 0) < 1000, "desktop-only layout contract");

  test("Today: primary action and Why are inside the first viewport without scrolling", async ({ page, viewport }) => {
    await page.goto("/");
    const cta = page.locator(".now-panel .button.primary");
    const why = page.locator(".why-list li").first();
    await expect(cta).toBeVisible();
    await expect(why).toBeVisible();
    expect(await bottomEdge(cta)).toBeLessThanOrEqual(viewport!.height);
    expect(await bottomEdge(why)).toBeLessThanOrEqual(viewport!.height);
    // Risk and due count share the first viewport via the rail.
    expect(await bottomEdge(page.locator(".rail-item").nth(1))).toBeLessThanOrEqual(viewport!.height);
  });

  test("Brain: the top-ranked diagnosis is visible without scrolling", async ({ page, viewport }) => {
    await page.goto("/#brain");
    const first = page.locator(".insight-card h2").first();
    await expect(first).toBeVisible();
    expect(await bottomEdge(first)).toBeLessThanOrEqual(viewport!.height);
  });

  test("Roadmap: heatmap header row is visible without scrolling", async ({ page, viewport }) => {
    await page.goto("/#roadmap");
    const header = page.locator(".heatmap thead");
    await expect(header).toBeVisible();
    expect(await bottomEdge(header)).toBeLessThanOrEqual(viewport!.height);
  });
});

test.describe("mobile 390px", () => {
  test.skip(({ viewport }) => (viewport?.width ?? 1000) > 500, "mobile-only layout contract");

  test("Today: the action precedes selection metadata", async ({ page }) => {
    await page.goto("/");
    const cta = page.locator(".now-panel .button.primary");
    const why = page.locator(".why-block");
    await expect(cta).toBeVisible();
    const ctaBox = await cta.boundingBox();
    const whyBox = await why.boundingBox();
    expect(ctaBox).not.toBeNull();
    expect(whyBox).not.toBeNull();
    expect(ctaBox!.y).toBeLessThan(whyBox!.y);
  });

  test("Brain and Roadmap render without horizontal overflow of the shell", async ({ page }) => {
    for (const route of ["/#brain", "/#roadmap"]) {
      await page.goto(route);
      const overflow = await page.evaluate(() => document.body.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(1);
    }
  });
});

test("decision-relevant text stays at or above 12px", async ({ page }) => {
  await page.goto("/");
  expect(await fontSizeOf(page.locator(".why-list li").first())).toBeGreaterThanOrEqual(12);
  expect(await fontSizeOf(page.locator(".rail-item strong").first())).toBeGreaterThanOrEqual(12);
  expect(await fontSizeOf(page.locator(".status-pill").first())).toBeGreaterThanOrEqual(12);
  await page.goto("/#library");
  expect(await fontSizeOf(page.locator(".problem-identity span").first())).toBeGreaterThanOrEqual(12);
});

test("a failed Solve submission lands on the problem workspace, not a dead route", async ({ page }) => {
  // Mock the write so live evidence is never mutated by layout tests; the mocked
  // response is a real bootstrap payload, exactly what the app expects back.
  const bootstrap = await page.request.get("/api/bootstrap").then(r => r.text());
  await page.route("**/api/attempts", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: bootstrap,
  }));
  await page.goto("/#solve");
  await expect(page.getByRole("button", { name: /Needed solution/ })).toBeVisible();
  await page.getByRole("button", { name: /Needed solution/ }).click();
  await expect(page).toHaveURL(/#problem\/\d+/);
  // The workspace actually renders — no blank screen.
  await expect(page.getByRole("navigation", { name: "Problem sections" })).toBeVisible();
  await expect(page.getByText("Skills this problem trains")).toBeVisible();
});
