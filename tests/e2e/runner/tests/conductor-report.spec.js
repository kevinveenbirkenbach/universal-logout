const { test, expect } = require("@playwright/test");

const FRAME = process.env.FRAME_HTTPS || "https://app.test.local/frame";
const OK_HOST = process.env.SWEPT_OK || "https://app.test.local";
const FAILING_HOST = process.env.SWEPT_FAILING || "https://absent.test.local";

async function reports(page) {
  return page.evaluate(() => window.__reports || []);
}

async function waitForDone(page) {
  await expect
    .poll(async () => (await reports(page)).some((r) => r.type === "done"), {
      message:
        "the conductor never reported done; the framing page would keep waiting forever",
      timeout: 30_000,
    })
    .toBe(true);
}

test.describe("conductor reporting", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("the framing page is told the sweep started, and with which domains", async ({
    page,
  }) => {
    await page.goto(FRAME, { waitUntil: "load" });

    await expect
      .poll(async () => (await reports(page)).some((r) => r.type === "start"), {
        timeout: 30_000,
      })
      .toBe(true);

    const start = (await reports(page)).find((r) => r.type === "start");
    expect(start.source).toBe("universal-logout");
    expect(start.domains).toEqual([OK_HOST, FAILING_HOST]);
  });

  test("every swept host is reported with its own verdict", async ({ page }) => {
    await page.goto(FRAME, { waitUntil: "load" });
    await waitForDone(page);

    const hosts = (await reports(page)).filter((r) => r.type === "host");
    const byHost = Object.fromEntries(hosts.map((r) => [r.host, r.ok]));

    expect(byHost[OK_HOST]).toBe(true);
    expect(byHost[FAILING_HOST]).toBe(false);
  });

  test("done carries the tally, counting the host that could not answer", async ({
    page,
  }) => {
    await page.goto(FRAME, { waitUntil: "load" });
    await waitForDone(page);

    const done = (await reports(page)).find((r) => r.type === "done");
    expect(done.total).toBe(2);
    expect(done.failed).toBe(1);
  });

  test("done arrives even though one host never answers", async ({ page }) => {
    await page.goto(FRAME, { waitUntil: "load" });
    await waitForDone(page);

    const kinds = (await reports(page)).map((r) => r.type);
    expect(kinds[0]).toBe("start");
    expect(kinds[kinds.length - 1]).toBe("done");
    expect(kinds.filter((k) => k === "done")).toHaveLength(1);
  });

  test("messages are addressed to the issuer origin, never broadcast", async ({
    page,
  }) => {
    await page.goto(FRAME, { waitUntil: "load" });
    await waitForDone(page);

    const origins = await page.evaluate(() => window.__origins || []);
    const conductorOrigin = await page.evaluate(
      () => new URL(document.getElementById("conductor").src).origin,
    );

    expect(origins.length).toBeGreaterThan(0);
    expect([...new Set(origins)]).toEqual([conductorOrigin]);
  });

  test("the swept host really was logged out, not merely reported as such", async ({
    page,
  }) => {
    const rootScoped = ["host_only", "domain_cookie", "secure_host_only", "secure_domain_cookie"];

    await page.goto(`${OK_HOST}/set`, { waitUntil: "domcontentloaded" });
    const before = (await page.context().cookies()).map((c) => c.name);
    for (const name of rootScoped) {
      expect(before, `${name} must exist before the sweep or this proves nothing`).toContain(name);
    }

    await page.goto(FRAME, { waitUntil: "load" });
    await waitForDone(page);

    const after = (await page.context().cookies()).map((c) => c.name);
    for (const name of rootScoped) {
      expect(after, `${name} is Path=/ and must not survive the sweep`).not.toContain(name);
    }
  });
});
