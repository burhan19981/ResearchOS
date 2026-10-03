import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/apiClient";
import { EmptyState, ErrorState, LoadingState } from "./States";

describe("LoadingState", () => {
  it("announces itself to assistive technology via role=status", () => {
    render(<LoadingState label="Loading experiments…" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading experiments…");
  });
});

describe("EmptyState", () => {
  it("renders an honest, specific empty-state message", () => {
    render(<EmptyState title="No experiments have been created yet." />);
    expect(screen.getByText("No experiments have been created yet.")).toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("renders the ApiError's message and an alert role", () => {
    render(<ErrorState error={new ApiError(404, { error: "NotFoundError", detail: "Project 5 does not exist." }, "fallback")} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Project 5 does not exist.")).toBeInTheDocument();
  });

  it("never shows a raw stack trace — only the error's short message", () => {
    const error = new Error("boom");
    // A real Error's multi-line stack trace lives on `.stack`, separate
    // from `.message` — confirm the component only ever reads `.message`.
    expect(error.stack).toContain("at ");
    render(<ErrorState error={error} />);
    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(screen.queryByText(/\bat\b.*\.tsx?:\d/)).not.toBeInTheDocument();
  });

  it("invokes retry when the Try again button is clicked", async () => {
    const retry = vi.fn();
    render(<ErrorState error={new Error("boom")} retry={retry} />);
    screen.getByRole("button", { name: /try again/i }).click();
    expect(retry).toHaveBeenCalledOnce();
  });
});
