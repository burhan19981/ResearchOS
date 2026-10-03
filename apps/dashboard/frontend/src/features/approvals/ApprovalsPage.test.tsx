import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetchRoutes } from "@/test/mockFetch";
import { renderWithProviders } from "@/test/testUtils";
import { ApprovalsPage } from "./ApprovalsPage";

const PENDING_APPROVAL = {
  id: 7,
  project_id: 1,
  stage: "RESEARCH_QUESTION_APPROVAL:3",
  entity_type: "ResearchQuestion",
  entity_id: 3,
  decision: "pending",
  comment: null,
  requested_at: "2026-01-01T00:00:00Z",
  decided_at: null,
};

function renderApprovals() {
  return renderWithProviders(<ApprovalsPage />);
}

describe("ApprovalsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.setItem("researchos.dashboard.selectedProjectId", "1");
  });

  it("shows an empty state when there are no approvals", async () => {
    vi.stubGlobal("fetch", mockFetchRoutes([["/api/v1/projects/1/approvals", []]]));
    window.localStorage.setItem("researchos.dashboard.selectedProjectId", "1");
    renderApprovals();
    expect(await screen.findByText("No approvals exist for this project yet.")).toBeInTheDocument();
  });

  it("lists a pending approval and opens the review dialog", async () => {
    window.localStorage.setItem("researchos.dashboard.selectedProjectId", "1");
    vi.stubGlobal("fetch", mockFetchRoutes([["/api/v1/projects/1/approvals", [PENDING_APPROVAL]]]));
    const user = userEvent.setup();
    renderApprovals();

    expect(await screen.findByText("Research Question")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Review" }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/RESEARCH_QUESTION_APPROVAL:3/)).toBeInTheDocument();
  });

  it("requires an explicit decision before Submit can be used", async () => {
    window.localStorage.setItem("researchos.dashboard.selectedProjectId", "1");
    vi.stubGlobal("fetch", mockFetchRoutes([["/api/v1/projects/1/approvals", [PENDING_APPROVAL]]]));
    const user = userEvent.setup();
    renderApprovals();

    await user.click(await screen.findByRole("button", { name: "Review" }));
    const submit = screen.getByRole("button", { name: /submit decision/i });
    expect(submit).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: "Approve" }));
    expect(submit).toBeEnabled();
  });

  it("submits the approval through the API and shows the resulting persisted status", async () => {
    window.localStorage.setItem("researchos.dashboard.selectedProjectId", "1");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/actions") && init?.method === "POST") {
        const body = JSON.parse(init.body as string);
        expect(body).toEqual({ action: "approve", comment: null });
        // No actor/is_human field is ever sent by the client.
        expect(body.actor).toBeUndefined();
        expect(body.is_human).toBeUndefined();
        return new Response(
          JSON.stringify({
            approval: { ...PENDING_APPROVAL, decision: "approved", decided_at: "2026-01-02T00:00:00Z" },
            entity_status: "approved",
          }),
          { status: 200 },
        );
      }
      if (url.includes("/approvals")) {
        return new Response(JSON.stringify([PENDING_APPROVAL]), { status: 200 });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderApprovals();

    await user.click(await screen.findByRole("button", { name: "Review" }));
    await user.click(screen.getByRole("radio", { name: "Approve" }));
    await user.click(screen.getByRole("button", { name: /submit decision/i }));

    await waitFor(() => expect(screen.getByText("Decision recorded.")).toBeInTheDocument());
    expect(screen.getByText("Approved")).toBeInTheDocument();
  });
});
