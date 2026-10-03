import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { queryClient } from "@/lib/queryClient";
import { mockFetchRoutes } from "./test/mockFetch";

const PROJECT = {
  id: 1,
  title: "Widget Durability Study",
  description: null,
  field: null,
  status: "active",
  current_stage: "STAGE_03_LITERATURE_SEARCH",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const EMPTY_COUNTS = {
  literature_items: 0,
  research_gaps: 0,
  novelty_assessments: 0,
  research_questions: 0,
  contribution_candidates: 0,
  experiments: 0,
  runs: 0,
  metrics: 0,
  analysis_records: 0,
  scientific_claims: 0,
  scientific_reviews: 0,
  pending_approvals: 0,
};

function stubHappyPathFetch() {
  return mockFetchRoutes([
    ["/api/v1/projects/1/overview", { project: PROJECT, current_stage: "STAGE_03_LITERATURE_SEARCH", counts: EMPTY_COUNTS }],
    ["/api/v1/projects/1", PROJECT],
    ["/api/v1/projects", [PROJECT]],
  ]);
}

describe("App", () => {
  beforeEach(() => {
    // BrowserRouter's history is backed by the real jsdom `window`,
    // which Vitest reuses across every test in this file — reset the
    // URL each time so a navigation test doesn't leak into the next.
    window.history.pushState({}, "", "/dashboard");
    // App.tsx imports the real, module-singleton `queryClient` (15s
    // staleTime) — without clearing it, a later test's fresh mock
    // response for the same query key is never actually fetched; the
    // still-fresh cached result from an earlier test is served instead.
    queryClient.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("boots without crashing and redirects to the Overview page", async () => {
    vi.stubGlobal("fetch", stubHappyPathFetch());
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Widget Durability Study" })).toBeInTheDocument();
  });

  it("renders the sidebar with primary navigation", async () => {
    vi.stubGlobal("fetch", stubHappyPathFetch());
    render(<App />);
    await screen.findByRole("heading", { name: "Widget Durability Study" });
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /overview/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /approvals/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /audit/i })).toBeInTheDocument();
  });

  it("navigates to the Audit page when its sidebar link is clicked", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      mockFetchRoutes([
        ["/api/v1/projects/1/overview", { project: PROJECT, current_stage: "STAGE_03_LITERATURE_SEARCH", counts: EMPTY_COUNTS }],
        ["/api/v1/projects/1/audit", []],
        ["/api/v1/projects/1", PROJECT],
        ["/api/v1/projects", [PROJECT]],
      ]),
    );
    render(<App />);
    await screen.findByRole("heading", { name: "Widget Durability Study" });

    await user.click(screen.getByRole("link", { name: /audit/i }));

    expect(await screen.findByRole("heading", { name: "Audit Log" })).toBeInTheDocument();
    expect(await screen.findByText("No audit events have been recorded yet.")).toBeInTheDocument();
  });

  it("shows an honest empty state, never a fabricated number, when there are no records", async () => {
    vi.stubGlobal("fetch", stubHappyPathFetch());
    render(<App />);
    await screen.findByRole("heading", { name: "Widget Durability Study" });
    // Every statistic renders literal 0, not a placeholder example value.
    const zeros = screen.getAllByText("0");
    expect(zeros.length).toBeGreaterThan(5);
  });

  it(
    "shows an error state when the overview request fails",
    async () => {
      vi.stubGlobal(
        "fetch",
        mockFetchRoutes([
          ["/api/v1/projects/1/overview", { error: "InternalServerError", detail: "boom" }, 500],
          ["/api/v1/projects/1", PROJECT],
          ["/api/v1/projects", [PROJECT]],
        ]),
      );
      render(<App />);
      // App.tsx uses the real, production `queryClient` (retry: 1 with
      // exponential backoff — see lib/queryClient.ts), not a
      // test-injected retry-disabled one, so surfacing isError takes
      // over a second in real time; both this test's own timeout and
      // waitFor's need enough headroom for that backoff to elapse.
      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument(), { timeout: 8000 });
    },
    10000,
  );
});
