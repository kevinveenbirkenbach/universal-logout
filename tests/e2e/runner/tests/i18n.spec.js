const { test, expect } = require("@playwright/test");
const fs = require("fs");

const CONDUCTOR = process.env.LOGOUT_HTTPS || "https://logout.test.local";
const CATALOGUE_FILE = process.env.CATALOGUE || "/work/translations.yml";

/**
 * Read the shipped catalogue without a YAML dependency.
 *
 * The file is a flat two-level mapping of unquoted scalars, which this parser
 * relies on. It throws on any line it cannot account for, so a catalogue that
 * grows quoting, nesting or block scalars fails the suite instead of silently
 * handing back a half-read catalogue.
 */
function readCatalogue(file) {
  const catalogue = {};
  let current = null;

  for (const [index, raw] of fs.readFileSync(file, "utf8").split("\n").entries()) {
    if (!raw.trim() || raw.trimStart().startsWith("#")) continue;

    const language = raw.match(/^([a-z]{2}):\s*$/);
    if (language) {
      current = language[1];
      catalogue[current] = {};
      continue;
    }

    const entry = raw.match(/^ {2}([a-z_]+): (.+)$/);
    if (entry && current) {
      catalogue[current][entry[1]] = entry[2];
      continue;
    }

    throw new Error(
      `${file}:${index + 1} is not a shape this reader knows: ${JSON.stringify(raw)}`,
    );
  }
  return catalogue;
}

const CATALOGUE = readCatalogue(CATALOGUE_FILE);
const LANGUAGES = Object.keys(CATALOGUE);
const RTL = LANGUAGES.filter((lang) => CATALOGUE[lang].dir === "rtl");

async function openConductor(page, query = "") {
  // domcontentloaded, not load: the sweep frames a deliberately absent host,
  // so waiting for every subresource would wait for that timeout on every test
  await page.goto(`${CONDUCTOR}/${query}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("h1");
}

test.describe("the conductor speaks the visitor's language", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("the catalogue reached the runner", () => {
    expect(LANGUAGES.length, `no languages parsed from ${CATALOGUE_FILE}`).toBeGreaterThan(1);
    expect(RTL.length, "no right-to-left language in the catalogue").toBeGreaterThan(0);
  });

  for (const lang of LANGUAGES) {
    test(`?lang=${lang} renders that language, not a fallback`, async ({ page }) => {
      const expected = CATALOGUE[lang];
      await openConductor(page, `?lang=${lang}`);

      await expect(page.locator("html")).toHaveAttribute("lang", lang);
      await expect(page.locator("html")).toHaveAttribute("dir", expected.dir);
      await expect(page.locator("h1")).toContainText(expected.heading);

      const body = await page.locator("body").innerText();
      for (const key of ["lead", "th_service", "th_status", "th_manual"]) {
        expect(body, `${lang}: ${key} is missing from the rendered page`).toContain(
          expected[key],
        );
      }
      expect(body, `${lang}: an unresolved template expression reached the page`).not.toContain(
        "Undefined",
      );
    });
  }
});

test.describe("right-to-left languages lay out right-to-left", () => {
  test.use({ ignoreHTTPSErrors: true });

  /**
   * Return the horizontal order of the table's first and last column header.
   *
   * Bounding boxes rather than a screenshot: the question is which side each
   * header sits on, and that answer must not depend on font rendering.
   */
  async function headerOrder(page) {
    const headers = page.locator("thead th");
    await expect(headers).toHaveCount(3);
    const first = await headers.first().boundingBox();
    const last = await headers.last().boundingBox();
    return { first: first.x, last: last.x };
  }

  test("the left-to-right control puts the first column on the left", async ({ page }) => {
    await openConductor(page, "?lang=en");
    const { first, last } = await headerOrder(page);
    expect(first, "sanity: en must lay out left-to-right").toBeLessThan(last);
  });

  for (const lang of RTL) {
    test(`${lang} puts the first column on the right`, async ({ page }) => {
      await openConductor(page, `?lang=${lang}`);

      const direction = await page.evaluate(
        () => getComputedStyle(document.body).direction,
      );
      expect(direction, `${lang}: dir="rtl" did not reach the computed style`).toBe("rtl");

      const { first, last } = await headerOrder(page);
      expect(
        first,
        `${lang}: the table still reads left-to-right — the page loads the LTR ` +
          `Bootstrap build, which does not flip every component for dir="rtl"`,
      ).toBeGreaterThan(last);
    });
  }
});

test.describe("the Accept-Language header decides when no override is given", () => {
  test.use({ ignoreHTTPSErrors: true, locale: "de-DE" });

  test("a German browser is served German without asking for it", async ({ page }) => {
    await openConductor(page);

    await expect(page.locator("html")).toHaveAttribute("lang", "de");
    await expect(page.locator("h1")).toContainText(CATALOGUE.de.heading);
  });
});

test.describe("an unknown language falls back rather than breaking", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("?lang=xx serves English", async ({ page }) => {
    await openConductor(page, "?lang=xx");

    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.locator("h1")).toContainText(CATALOGUE.en.heading);
  });
});
