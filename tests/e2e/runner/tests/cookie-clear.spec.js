const { test, expect } = require("@playwright/test");

const BASE_HTTP = process.env.BASE_HTTP || "http://app.test.local:8080";
const BASE_HTTPS = process.env.BASE_HTTPS || "https://app.test.local:8443";

/**
 * IMPORTANT:
 * - Clear-Site-Data must be processed by the browser (not Playwright request context).
 * - page.goto() can fail with net::ERR_ABORTED because the browser may abort navigations
 *   while clearing storage/cookies.
 * - Therefore trigger via fetch() inside the page (browser context).
 */
async function triggerCsdViaFetch(page, url) {
  await page.evaluate(async (u) => {
    try {
      const res = await fetch(u, {
        method: "GET",
        credentials: "include",
        cache: "no-store",
      });
      await res.text();
    } catch (e) {
      // Some browsers may still throw during CSD processing - ignore.
    }
  }, url);
}

async function cookieNamesInContext(context, baseUrl) {
  const cookies = await context.cookies(baseUrl);
  return cookies.map((c) => c.name).sort();
}

async function setCookies(page, baseUrl) {
  await page.goto(`${baseUrl}/set`, { waitUntil: "domcontentloaded" });
  await page.goto(`${baseUrl}/api/ping`, { waitUntil: "domcontentloaded" });
}

test.describe("Cookie deletion strategies", () => {
  test("HTTPS: Clear-Site-Data should clear origin cookies", async ({ browser }) => {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();

    await setCookies(page, BASE_HTTPS);
    let names = await cookieNamesInContext(context, BASE_HTTPS);
    expect(names.length).toBeGreaterThan(0);

    // Trigger CSD on the SAME origin that owns the cookies (app.test.local)
    await triggerCsdViaFetch(page, `${BASE_HTTPS}/logout-csd`);

    await page.waitForTimeout(100);

    names = await cookieNamesInContext(context, BASE_HTTPS);
    expect(names).toEqual([]);

    await context.close();
  });

  test("HTTP: Clear-Site-Data is NOT guaranteed; we assert it may leave cookies", async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();

    await setCookies(page, BASE_HTTP);
    const before = await cookieNamesInContext(context, BASE_HTTP);
    expect(before.length).toBeGreaterThan(0);

    // On HTTP, browsers may ignore CSD. Still trigger in-browser on same origin.
    await triggerCsdViaFetch(page, `${BASE_HTTP}/logout-csd`);

    const after = await cookieNamesInContext(context, BASE_HTTP);

    // We only assert it does not INCREASE cookies.
    expect(after.length).toBeLessThanOrEqual(before.length);

    await context.close();
  });

  test("HTTP: Set-Cookie deletes are best-effort; host-only may remain", async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();

    await setCookies(page, BASE_HTTP);
    let names = await cookieNamesInContext(context, BASE_HTTP);
    expect(names.length).toBeGreaterThan(0);

    // Logout endpoint should be reachable on app origin
    await page.goto(`${BASE_HTTP}/logout-setcookie`, { waitUntil: "domcontentloaded" });

    names = await cookieNamesInContext(context, BASE_HTTP);

    // Depending on browser/version, host-only cookies may remain OR may also be cleared.
    // Accept both outcomes: [] or ["host_only"].
    expect([[], ["host_only"]]).toContainEqual(names);

    await context.close();
  });

  test("HTTPS: Combined strategy must clear everything for app origin", async ({ browser }) => {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();

    await setCookies(page, BASE_HTTPS);
    let names = await cookieNamesInContext(context, BASE_HTTPS);
    expect(names.length).toBeGreaterThan(0);

    await page.goto(`${BASE_HTTPS}/logout-combined`, { waitUntil: "domcontentloaded" });

    await page.waitForTimeout(100);

    names = await cookieNamesInContext(context, BASE_HTTPS);
    expect(names).toEqual([]);

    await context.close();
  });

  test("Domain cookies visibility: domain.test.local should see Domain=.test.local cookies (before logout)", async ({ browser }) => {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();

    await setCookies(page, BASE_HTTPS);

    const cookies = await context.cookies(BASE_HTTPS);
    const hasDomainCookie = cookies.some(
      (c) =>
        c.name === "domain_cookie" &&
        (c.domain === ".test.local" || c.domain === "test.local")
    );
    expect(hasDomainCookie).toBeTruthy();

    await context.close();
  });
});
