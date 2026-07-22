import { expect, test, type Locator, type Page } from "@playwright/test";

async function bottomEdge(locator: Locator) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return box!.y + box!.height;
}

async function fontSizeOf(locator: Locator) {
  return locator.evaluate(element => parseFloat(getComputedStyle(element).fontSize));
}

async function openAdHocSession(page: Page, search: string) {
  const listing = await page.request.get(`/api/problems?search=${search}`).then(r => r.json());
  const envelope = await page.request
    .post(`/api/problems/${listing.items[0].id}/practice-sessions`, { data: {} })
    .then(r => r.json());
  await page.goto(`/#solve/${envelope.session.id}`);
  await expect(page.locator(".session-bar")).toBeVisible();
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
    expect(await bottomEdge(page.locator(".rail-item").nth(1))).toBeLessThanOrEqual(viewport!.height);
  });

  test("Solve: command bar, paper brief, and sticky hint rail share the first viewport", async ({ page, viewport }) => {
    await openAdHocSession(page, "max+area+of+island");
    expect(await bottomEdge(page.locator(".session-bar"))).toBeLessThanOrEqual(200);
    await expect(page.locator(".paper-framework .framework-column")).toHaveCount(3);
    const rail = page.locator(".hint-rail");
    await expect(rail).toBeVisible();
    const railBox = await rail.boundingBox();
    expect(railBox!.width).toBeGreaterThanOrEqual(300);
    expect(railBox!.y).toBeLessThanOrEqual(viewport!.height);
    // No drawer toggle on a two-column desktop.
    await expect(page.locator(".hint-drawer-toggle")).toBeHidden();
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

  test("Solve at 390px: no horizontal overflow, stacked framework, 44px touch targets", async ({ page }) => {
    await openAdHocSession(page, "pacific+atlantic");
    const overflow = await page.evaluate(() => document.body.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);

    // Full-width LeetCode CTA and >=44px commands.
    const ctaBox = await page.locator(".leetcode-cta").boundingBox();
    const viewportWidth = await page.evaluate(() => window.innerWidth);
    expect(ctaBox!.width).toBeGreaterThanOrEqual(viewportWidth * 0.8);
    expect(ctaBox!.height).toBeGreaterThanOrEqual(44);
    const finishBox = await page.locator(".finish-cta").boundingBox();
    expect(finishBox!.height).toBeGreaterThanOrEqual(44);

    // Framework columns stack.
    const columns = page.locator(".framework-column");
    const first = await columns.nth(0).boundingBox();
    const second = await columns.nth(1).boundingBox();
    expect(second!.y).toBeGreaterThan(first!.y + first!.height - 2);

    // Hint drawer opens with a >=44px reveal control.
    await page.locator(".hint-drawer-toggle").click();
    const revealBox = await page.getByRole("button", { name: "Reveal H1", exact: true }).boundingBox();
    expect(revealBox!.height).toBeGreaterThanOrEqual(44);

    // Finish opens as a bottom sheet pinned to the lower edge.
    await page.locator(".finish-cta").click();
    const sheet = await page.locator(".finish-sheet").boundingBox();
    const viewportHeight = await page.evaluate(() => window.innerHeight);
    expect(sheet!.y + sheet!.height).toBeGreaterThanOrEqual(viewportHeight - 2);
  });

  test("Library rows keep real action buttons at 44px and no overflow", async ({ page }) => {
    await page.goto("/#library");
    await expect(page.locator(".problem-row").first()).toBeVisible();
    const overflow = await page.evaluate(() => document.body.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    const practice = await page.locator(".practice-button").first().boundingBox();
    expect(practice!.height).toBeGreaterThanOrEqual(44);
    const external = await page.locator(".external-button").first().boundingBox();
    expect(external!.height).toBeGreaterThanOrEqual(44);
    // Pattern metadata is retained on mobile rows.
    await expect(page.locator(".problem-identity > span").nth(1)).toContainText(/·/);
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
  await page.goto("/#library");
  expect(await fontSizeOf(page.locator(".problem-identity span").first())).toBeGreaterThanOrEqual(12);
  expect(await fontSizeOf(page.locator(".status-pill").first())).toBeGreaterThanOrEqual(12);
});
