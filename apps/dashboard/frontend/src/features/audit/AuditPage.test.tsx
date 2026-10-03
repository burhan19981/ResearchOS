import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetchRoutes } from "@/test/mockFetch";
import { renderWithProviders } from "@/test/testUtils";
import { AuditPage } from "./AuditPage";

describe("AuditPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders real audit events, most recent first, never fabricated", async () => {
    window.localStorage.setItem("researchos.dashboard.selectedProjectId", "1");
    vi.stubGlobal(
      "fetch",
      mockFetchRoutes([
        [
          "/api/v1/projects/1/audit",
          [
            { id: 1, project_id: 1, event_type: "analysis.comparison_created", actor: "user:tester", description: "First", metadata: null, created_at: "2026-01-01T00:00:00Z" },
            { id: 2, project_id: 1, event_type: "analysis.claim_approved", actor: "user:dashboard", description: "Second", metadata: null, created_at: "2026-01-02T00:00:00Z" },
          ],
        ],
      ]),
    );

    renderWithProviders(<AuditPage />);

    expect(await screen.findByText("analysis.claim_approved")).toBeInTheDocument();
    expect(screen.getByText("analysis.comparison_created")).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    // Header row + 2 data rows, most recent event first.
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent("analysis.claim_approved");
  });

  it("shows an honest empty state with no fabricated audit events", async () => {
    window.localStorage.setItem("researchos.dashboard.selectedProjectId", "1");
    vi.stubGlobal("fetch", mockFetchRoutes([["/api/v1/projects/1/audit", []]]));
    renderWithProviders(<AuditPage />);
    expect(await screen.findByText("No audit events have been recorded yet.")).toBeInTheDocument();
  });
});
