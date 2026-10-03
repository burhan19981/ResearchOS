import { expect, test } from "@playwright/test";

/**
 * The one end-to-end smoke test Dashboard V1 spec section 31 asks
 * for: open dashboard -> select project -> load overview -> navigate
 * pipeline -> open experiment/run -> open approval center -> return
 * to overview. Runs against the REAL FastAPI backend (seeded with a
 * small, obviously-synthetic project by
 * apps/dashboard/api/e2e_seed_and_serve.py) and the real production
 * frontend build — nothing here is mocked.
 */
test("full smoke path through the dashboard", async ({ page }) => {
  await page.goto("/dashboard");

  // Project selector defaults to the seeded project and the overview
  // loads real, non-fabricated data for it.
  await expect(page.getByRole("heading", { name: "E2E Smoke Test Project" })).toBeVisible();
  await expect(page.getByText("1", { exact: true }).first()).toBeVisible(); // at least one real count > 0

  // Navigate to the Pipeline page via the sidebar.
  await page.getByRole("link", { name: "Pipeline" }).click();
  await expect(page.getByRole("heading", { name: "Research Pipeline" })).toBeVisible();
  await expect(page.getByText("Current").first()).toBeVisible();

  // Navigate to Experiments, open the seeded experiment, open its run.
  await page.getByRole("link", { name: "Experiments & Runs" }).click();
  await expect(page.getByRole("heading", { name: "Experiments" })).toBeVisible();
  await page.getByRole("link", { name: "E2E Sample Experiment" }).click();
  await expect(page.getByRole("heading", { name: "E2E Sample Experiment" })).toBeVisible();
  // The expanded synthetic seed includes pending and completed runs.
  await page.getByRole("row").filter({ hasText: "Succeeded" }).first().getByRole("link").click();
  await expect(page.getByRole("heading", { name: /^Run #\d+$/ })).toBeVisible();
  await expect(page.getByText("accuracy", { exact: true })).toBeVisible();

  // Open the Approval Center and confirm the seeded pending approval
  // is real, then walk through (without submitting) the review dialog.
  await page.getByRole("link", { name: "Approvals" }).click();
  await expect(page.getByRole("heading", { name: "Approval Center" })).toBeVisible();
  await expect(page.getByText("Research Question")).toBeVisible();
  // The research-question request is seeded before the other requests.
  await page.getByRole("button", { name: "Review", exact: true }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText(/RESEARCH_QUESTION_APPROVAL/)).toBeVisible();
  await page.keyboard.press("Escape");

  // Return to Overview.
  await page.getByRole("link", { name: "Overview" }).click();
  await expect(page.getByRole("heading", { name: "E2E Smoke Test Project" })).toBeVisible();
});
