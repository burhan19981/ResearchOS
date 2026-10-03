import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusPill } from "./StatusPill";

describe("StatusPill", () => {
  it("renders the humanized status text alongside an icon", () => {
    render(<StatusPill status="human_approved" />);
    expect(screen.getByText("Human Approved")).toBeInTheDocument();
  });

  it("never communicates state through color alone: an icon is always present", () => {
    const { container } = render(<StatusPill status="rejected" />);
    expect(container.querySelector("svg")).toBeInTheDocument();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
  });

  it("accepts an explicit label override", () => {
    render(<StatusPill status="ready_for_human_review" label="Ready for review" />);
    expect(screen.getByText("Ready for review")).toBeInTheDocument();
  });
});
