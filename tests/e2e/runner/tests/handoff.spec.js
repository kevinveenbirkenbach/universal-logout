const { test, expect } = require("@playwright/test");

const HANDOFF_A = process.env.HANDOFF_A || "https://handoff-a.test.local";
const HANDOFF_B = process.env.HANDOFF_B || "https://handoff-b.test.local";
const FRAME = process.env.FRAME_HTTPS || "https://app.test.local/frame";

async function waitForSweep(page) {
  await expect(page.locator("#status-0")).not.toHaveClass(/status-in-process/, {
    timeout: 30_000,
  });
  await page.waitForTimeout(2_000);
}

test.describe("hand-off between sibling conductors", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("a top-level conductor continues to its sibling once its sweep is done", async ({
    page,
  }) => {
    await page.goto(`${HANDOFF_A}/`, { waitUntil: "load" });
    await page.waitForURL((url) => url.origin === HANDOFF_B, { timeout: 30_000 });

    const landed = new URL(page.url());
    expect(landed.searchParams.get("handoff")).toBe("");
  });

  test("the last conductor of the chain stays on its own page", async ({ page }) => {
    await page.goto(`${HANDOFF_B}/?handoff=`, { waitUntil: "load" });
    await expect(page.locator("#iframe-warning")).toBeHidden();
    await waitForSweep(page);

    expect(new URL(page.url()).origin).toBe(HANDOFF_B);
  });

  test("a framed conductor asks the framing page to continue instead of navigating", async ({
    page,
  }) => {
    await page.goto(`${FRAME}?conductor=${encodeURIComponent(`${HANDOFF_A}/`)}`, {
      waitUntil: "load",
    });

    await expect
      .poll(
        async () =>
          (await page.evaluate(() => window.__reports || [])).find(
            (r) => r.type === "handoff",
          ),
        {
          message: "the framed conductor never reported the hand-off to the framing page",
          timeout: 30_000,
        },
      )
      .toBeTruthy();

    const handoff = (await page.evaluate(() => window.__reports)).find(
      (r) => r.type === "handoff",
    );
    const target = new URL(handoff.url);
    expect(target.origin).toBe(HANDOFF_B);
    expect(target.searchParams.get("handoff")).toBe("");

    const conductor = page.frames().find((frame) => frame.url().startsWith(HANDOFF_A));
    expect(conductor, "the framed conductor navigated itself away").toBeTruthy();
  });

  test("a conductor ignores a hand-off target it was not configured with", async ({
    page,
  }) => {
    await page.goto(
      `${HANDOFF_A}/?handoff=${encodeURIComponent("https://app.test.local")}`,
      { waitUntil: "load" },
    );
    await waitForSweep(page);

    expect(new URL(page.url()).origin).toBe(HANDOFF_A);
  });
});
