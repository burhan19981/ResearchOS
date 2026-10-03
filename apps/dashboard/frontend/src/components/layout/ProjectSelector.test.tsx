import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetchRoutes } from "@/test/mockFetch";
import { renderWithProviders } from "@/test/testUtils";
import { useProjectContext } from "@/lib/ProjectContext";
import { ProjectSelector } from "./ProjectSelector";

const PROJECT_A = { id: 1, title: "Project A", description: null, field: null, status: "active", current_stage: null, created_at: "", updated_at: "" };
const PROJECT_B = { id: 2, title: "Project B", description: null, field: null, status: "active", current_stage: null, created_at: "", updated_at: "" };

function Harness() {
  const { selectedProjectId } = useProjectContext();
  return (
    <div>
      <ProjectSelector />
      <p data-testid="selected">{selectedProjectId ?? "none"}</p>
    </div>
  );
}

describe("ProjectSelector", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("defaults to the first project when none is selected", async () => {
    vi.stubGlobal("fetch", mockFetchRoutes([["/api/v1/projects", [PROJECT_A, PROJECT_B]]]));
    renderWithProviders(<Harness />);
    await waitFor(() => expect(screen.getByTestId("selected")).toHaveTextContent("1"));
  });

  it("switching the selector updates the selected project id — never mixing project data", async () => {
    vi.stubGlobal("fetch", mockFetchRoutes([["/api/v1/projects", [PROJECT_A, PROJECT_B]]]));
    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    await screen.findByLabelText("Select project");

    await user.selectOptions(screen.getByLabelText("Select project"), "2");

    expect(screen.getByTestId("selected")).toHaveTextContent("2");
  });
});
