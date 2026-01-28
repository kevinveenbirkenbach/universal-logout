// @ts-check
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  use: {
    // Self-signed cert in test nginx -> ignore TLS errors
    ignoreHTTPSErrors: true,
    // Be explicit: cookies are per-browser-context
    trace: "on-first-retry",
  },
});
