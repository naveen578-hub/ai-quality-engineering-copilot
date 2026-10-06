import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

type AuditEntry = {
  view: string;
  violations: Array<{
    id: string;
    impact: string | null;
    description: string;
    help: string;
    helpUrl: string;
    nodes: Array<{ target: string[]; summary: string }>;
  }>;
};

const auditEntries: AuditEntry[] = [];

test("login and workspace views are accessible", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await page.emulateMedia({ reducedMotion: "reduce" });

  async function audit(view: string) {
    const result = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
      .analyze();

    auditEntries.push({
      view,
      violations: result.violations.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        description: violation.description,
        help: violation.help,
        helpUrl: violation.helpUrl,
        nodes: violation.nodes.map((node) => ({
          target: node.target.map(String),
          summary: node.failureSummary ?? "",
        })),
      })),
    });
  }

  await page.goto("/");
  await expect(page.getByLabel("Username")).toBeVisible();
  await audit("login");

  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("changeme123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "AI Quality Engineering Copilot" })).toBeVisible({ timeout: 30_000 });

  const tabs = page.locator("nav.top-level-tabs").getByRole("tab");
  const tabCount = await tabs.count();
  for (let index = 0; index < tabCount; index += 1) {
    const tab = tabs.nth(index);
    const label = (await tab.innerText()).replace(/^\s*\d+\s*/, "").trim();
    await tab.click();
    await audit(label || `workspace-tab-${index + 1}`);
  }

  const report = {
    generatedAt: new Date().toISOString(),
    url: testInfo.project.use.baseURL,
    gate: "Fail on critical or serious axe violations; all impacts are included below.",
    audits: auditEntries,
  };
  const reportPath = path.resolve("test-results/accessibility-report.json");
  await mkdir(path.dirname(reportPath), { recursive: true });
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
  await testInfo.attach("axe-accessibility-report", {
    body: JSON.stringify(report, null, 2),
    contentType: "application/json",
  });

  const blockingViolations = auditEntries.flatMap((entry) =>
    entry.violations
      .filter((violation) => violation.impact === "critical" || violation.impact === "serious")
      .map((violation) => `${entry.view}: ${violation.id} (${violation.impact})`),
  );
  expect(blockingViolations, "Critical and serious axe violations").toEqual([]);
});