import { defineConfig } from "@playwright/test";

// Tests de bout en bout : le vrai moteur en mode simulation (`halloween-cli api --simulate`, pilotes
// fictifs, dossier de données neuf à chaque lancement) sert le vrai build de l'interface.
// Navigateur : celui de Playwright (`npx playwright install chromium`), ou un Chromium déjà présent
// désigné par E2E_CHROMIUM (chemin de l'exécutable).
const PORT = 8090;

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 8_000 },
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1400, height: 950 },
    launchOptions: process.env.E2E_CHROMIUM ? { executablePath: process.env.E2E_CHROMIUM, args: ["--no-sandbox"] } : {},
    trace: "retain-on-failure",
  },
  webServer: {
    command: `rm -rf .e2e-data && mkdir .e2e-data && echo '{}' > .e2e-data/config.json && uv run --project ../engine halloween-cli --data-dir .e2e-data api --simulate --host 127.0.0.1 --port ${PORT} --ui-dir dist`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
