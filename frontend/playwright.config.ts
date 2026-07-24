import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:8010",
    channel: "chrome",
    trace: "retain-on-failure",
    screenshot: "only-on-failure"
  },
  projects: [
    { name: "mobile-375", use: { viewport: { width: 375, height: 812 } } },
    { name: "tablet-768", use: { viewport: { width: 768, height: 1024 } } },
    { name: "desktop-1280", use: { viewport: { width: 1280, height: 900 } } },
    { name: "wide-1600", use: { viewport: { width: 1600, height: 1000 } } }
  ],
  webServer: {
    command: "..\\oms\\venv312\\Scripts\\python.exe -m alembic -c ..\\oms\\alembic.ini upgrade head && ..\\oms\\venv312\\Scripts\\python.exe -m uvicorn app.main:app --app-dir ..\\oms --host 127.0.0.1 --port 8010",
    url: "http://127.0.0.1:8010/health/live",
    env: {
      DATABASE_URL: "sqlite:///playwright.db",
      APP_ENV: "test",
      AUTH_MODE: "local"
    },
    reuseExistingServer: false,
    timeout: 120_000
  }
});
