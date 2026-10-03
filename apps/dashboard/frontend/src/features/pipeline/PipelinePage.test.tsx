import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetchRoutes } from "@/test/mockFetch";
import { renderWithProviders } from "@/test/testUtils";
import { PipelinePage } from "./PipelinePage";

function makeStages() {
  const names = ["STAGE_01_IDEA", "STAGE_02_INITIAL_VALIDATION", "STAGE_03_LITERATURE_SEARCH", "STAGE_04_LITERATURE_MAPPING"];
  return names.map((stage, order) => ({ stage, order, is_current: order === 2, is_completed: order < 2 }));
}

describe("PipelinePage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.setItem("researchos.dashboard.selectedProjectId", "1");
  });

  it("renders the real workflow stage list with the current stage marked", async () => {
    window.localStorage.setItem("researchos.dashboard.selectedProjectId", "1");
    vi.stubGlobal(
      "fetch",
      mockFetchRoutes([
        [
          "/api/v1/projects/1/pipeline",
          {
            project_id: 1,
            project_status: "active",
            current_stage: "STAGE_03_LITERATURE_SEARCH",
            stages: makeStages(),
            allowed_transitions: [{ target_stage: "STAGE_04_LITERATURE_MAPPING", policy: "auto_allowed", direction: "forward" }],
          },
        ],
      ]),
    );

    renderWithProviders(<PipelinePage />);

    expect(await screen.findByText("Stage 03 Literature Search")).toBeInTheDocument();
    expect(screen.getByText("Current")).toBeInTheDocument();
    expect(screen.getByText("Allowed next")).toBeInTheDocument();
    expect(screen.getAllByText(/Literature Mapping/).length).toBeGreaterThan(0);
  });

  it("shows a plain message when no transitions are currently allowed", async () => {
    window.localStorage.setItem("researchos.dashboard.selectedProjectId", "1");
    vi.stubGlobal(
      "fetch",
      mockFetchRoutes([
        [
          "/api/v1/projects/1/pipeline",
          { project_id: 1, project_status: "paused", current_stage: "STAGE_03_LITERATURE_SEARCH", stages: makeStages(), allowed_transitions: [] },
        ],
      ]),
    );

    renderWithProviders(<PipelinePage />);
    expect(await screen.findByText("No transitions are currently allowed for this project.")).toBeInTheDocument();
  });
});
