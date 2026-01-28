// tests/e2e/runner/playwright.config.js
// @ts-check

/**
 * Playwright configuration for E2E tests.
 *
 * This setup runs all tests against:
 *  - Chromium (Chrome-like)
 *  - Firefox
 *  - WebKit (Safari-like)
 *
 * The goal is to verify browser-agnostic behavior, especially
 * security-relevant features like cookie deletion and Clear-Site-Data.
 */

const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  // Directory where the test files are located
  testDir: "./tests",

  // Global timeout per test
  timeout: 30_000,

  // Run tests sequentially for deterministic results in Docker
  workers: 1,

  // No retries to keep failures explicit and reproducible
  retries: 0,

  // Reporters:
  // - "list" for readable CLI output
  // - "html" for optional local inspection after failures
  reporter: [
    ["list"],
    ["html", { open: "never" }],
  ],

  // Shared settings for all browsers
  use: {
    // Docker-friendly: no visible browser window
    headless: true,

    // Required for self-signed certificates in the E2E setup
    ignoreHTTPSErrors: true,

    // Helpful diagnostics on failure
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  // Run the same test suite in multiple browser engines
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
      },
    },
    {
      name: "firefox",
      use: {
        ...devices["Desktop Firefox"],
      },
    },
    {
      name: "webkit",
      use: {
        ...devices["Desktop Safari"],
      },
    },
  ],
});
