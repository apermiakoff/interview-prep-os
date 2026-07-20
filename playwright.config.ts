import { defineConfig, devices } from "@playwright/test";

const externalBaseURL = process.env.PLAYWRIGHT_BASE_URL;
const baseURL = externalBaseURL || "http://127.0.0.1:8788";

export default defineConfig({
  testDir: "frontend/e2e",
  timeout: 30_000,
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  // Hermetic by default: a disposable copy of the live DB on a private port, so
  // e2e runs never mutate real evidence or depend on the running deployment.
  ...(externalBaseURL
    ? {}
    : {
        webServer: {
          command: "uv run python scripts/run_e2e_server.py",
          url: "http://127.0.0.1:8788/api/health",
          reuseExistingServer: false,
          timeout: 90_000,
        },
      }),
  projects: [
    // The laptop this is actually used on: 1366x768.
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 768 } } },
    // Narrow phone: 390px wide (Chromium-based device so no extra browser install).
    { name: "mobile", use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 } } },
  ],
});
