/**
 * Capture the dashboard for the README.
 *
 * Drives a real intent through a running coordinator rather than mocking one,
 * so every screenshot shows the system actually doing what it claims to do.
 * That also means the images cannot drift from reality without the run
 * failing first.
 *
 * Requires a coordinator with the logistics demo seeded, the dashboard
 * serving, and an LLM configured:
 *
 *   npx playwright install chromium
 *   node ui/scripts/capture-screenshots.mjs [baseUrl] [outDir]
 *
 * Takes a few minutes: the negotiation is real, and so is the model call.
 */

import { mkdir } from "node:fs/promises";
import path from "node:path";

import { chromium } from "playwright";

const BASE = process.argv[2] ?? "http://127.0.0.1:3000";
const OUT = process.argv[3] ?? "docs/images";

const INTENT =
  "A storm has closed the Port of Rotterdam. Reroute our shipment of " +
  "refrigerated pharmaceuticals from Hamburg to Madrid so it still arrives " +
  "within 5 days, and confirm cold-chain warehouse space at the destination.";

const shot = async (page, name, opts = {}) => {
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, ...opts });
  console.log(`  captured ${name}.png`);
};

/** Wait for text to appear anywhere on the page. */
async function waitForText(page, text, timeout = 180_000) {
  await page.waitForFunction(
    (t) => document.body.innerText.includes(t),
    text,
    { timeout, polling: 500 },
  );
}

/** The graph mounts zoomed to a corner; fit it so the panel is not empty. */
async function fitGraph(page) {
  const fit = page.getByRole("button", { name: "Fit View" });
  if (await fit.isVisible().catch(() => false)) {
    await fit.click();
    await page.waitForTimeout(900);
  }
}

async function main() {
  await mkdir(OUT, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
  });
  const page = await context.newPage();

  console.log("→ negotiation");
  await page.goto(`${BASE}/intent`, { waitUntil: "networkidle" });
  await page.getByPlaceholder(/Describe your intent/i).fill(INTENT);
  await page.keyboard.press("Enter");

  // The plan gate is the interesting state: the coordinator has decomposed
  // the intent, discovered agents, negotiated offers and built a plan — and
  // is waiting for a human before any of it runs.
  await waitForText(page, "Requires Approval");
  await page.waitForTimeout(1200);
  await fitGraph(page);
  await shot(page, "01-negotiation-plan");

  await page.getByRole("button", { name: "Approve", exact: true }).click();

  // "Complete" is also the label of the last phase in the pipeline, which is
  // in the DOM from the moment the page loads. Wait on the progress readout
  // instead — it only reaches 100% when the session actually finishes.
  await waitForText(page, "100%", 300_000);
  await page.waitForTimeout(2500);
  await fitGraph(page);
  await shot(page, "02-negotiation-complete");

  // The execution graph, with the plan actually carried out.
  const results = page.getByRole("tab", { name: "Results" });
  if (await results.isVisible().catch(() => false)) {
    await results.click();
    await page.waitForTimeout(1000);
    await shot(page, "03-results");
  }

  const pages = [
    ["04-dashboard", "/"],
    ["05-agents", "/agents"],
    ["06-ibac", "/ibac"],
    ["07-history", "/history"],
    ["08-audit", "/audit"],
  ];

  for (const [name, route] of pages) {
    console.log(`→ ${route}`);
    await page.goto(`${BASE}${route}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(2000);
    await shot(page, name);
  }

  await browser.close();
  console.log(`\ndone — ${OUT}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
