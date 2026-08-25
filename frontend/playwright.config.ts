import { defineConfig } from "@playwright/test";

// `python` is not a command on a stock macOS or a modern Linux, and this default
// sent the browser suite into "command not found" on every developer machine that
// is not the one it was written on. CI works only because the workflow sets
// PYTHON_BIN explicitly. Same defect as the pre-push hook's, third instance.
// The repository venv comes first: it is the only interpreter carrying the pins.
import { existsSync } from "node:fs";

const pythonCandidates = [
  process.env.PYTHON_BIN,
  "../oms/venv/bin/python",
  "../.venv/bin/python",
].filter((candidate): candidate is string => Boolean(candidate));

const python =
  pythonCandidates.find((candidate) => candidate === process.env.PYTHON_BIN || existsSync(candidate)) ??
  "python3";

export default defineConfig({
  testDir: "./tests",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  // One retry, so that a timing-dependent test is reported as *flaky* rather
  // than failed. This is not a way to make red go green: `audit_browser_evidence.py`
  // prints every flaky test by name and treats the count as a standing debt.
  // Measured reason for it: "pipeline deploys an immutable snapshot" waits for the
  // UI to read SUCCEEDED and then reads the job's result, and under load the
  // result lands after the status does -- observed failing three runs in a row
  // and passing the next.
  retries: 1,
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
    command: `${python} -c "from pathlib import Path; Path('playwright.db').unlink(missing_ok=True)" && ${python} -m alembic -c ../oms/alembic.ini upgrade head && ${python} -m uvicorn app.main:app --app-dir ../oms --host 127.0.0.1 --port 8010`,
    url: "http://127.0.0.1:8010/health/live",
    env: {
      DATABASE_URL: process.env.PLAYWRIGHT_DATABASE_URL || "sqlite:///playwright.db",
      APP_ENV: "test",
      AUTH_MODE: "local",
      CONNECTOR_ALLOW_PRIVATE_NETWORKS: "true",
      CONNECTOR_SECRET_KEY: "playwright-isolated-connector-key"
    },
    reuseExistingServer: false,
    timeout: 120_000
  }
});
