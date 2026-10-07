import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45000,
  expect: { timeout: 10000 },
  use: {
    baseURL: "http://127.0.0.1:18789",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.CHROME_BIN
      ? { executablePath: process.env.CHROME_BIN }
      : {},
  },
  webServer: {
    command:
      "mkdir -p .e2e && CGO_ENABLED=0 go build -o .e2e/wiki-ui . && python tests/serve.py",
    url: "http://127.0.0.1:18789/healthz",
    timeout: 120000,
    reuseExistingServer: false,
  },
});
