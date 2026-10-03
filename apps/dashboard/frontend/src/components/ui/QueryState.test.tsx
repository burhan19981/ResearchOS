import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QueryState } from "./QueryState";

describe("QueryState", () => {
  it("shows the spinner while a request is actually in flight", () => {
    render(
      <QueryState isLoading data={undefined} isError={false} error={null} refetch={vi.fn()} fetchStatus="fetching">
        {() => <p>content</p>}
      </QueryState>,
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows an honest message instead of an eternal spinner when the query is disabled (fetchStatus idle, no data)", () => {
    // Regression test: every project-scoped hook passes `enabled:
    // projectId !== null`. On a database with zero projects, that
    // query never runs — data stays undefined and isLoading stays
    // false forever, since no fetch was ever attempted. Before this
    // fix, QueryState's fallback treated `data === undefined` as
    // "still loading" unconditionally, so every page except Overview
    // (which had its own separate manual guard) spun forever.
    render(
      <QueryState isLoading={false} data={undefined} isError={false} error={null} refetch={vi.fn()} fetchStatus="idle">
        {() => <p>content</p>}
      </QueryState>,
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText("No project selected")).toBeInTheDocument();
  });

  it("still shows the spinner (not the disabled message) when fetchStatus is undefined — a query mid-first-fetch before isLoading updates", () => {
    render(
      <QueryState isLoading={false} data={undefined} isError={false} error={null} refetch={vi.fn()}>
        {() => <p>content</p>}
      </QueryState>,
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the error state and never the disabled message when isError is true", () => {
    render(
      <QueryState isLoading={false} data={undefined} isError error={new Error("boom")} refetch={vi.fn()} fetchStatus="idle">
        {() => <p>content</p>}
      </QueryState>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("No project selected")).not.toBeInTheDocument();
  });

  it("renders children on success", () => {
    render(
      <QueryState isLoading={false} data={{ n: 1 }} isError={false} error={null} refetch={vi.fn()} fetchStatus="idle">
        {(d) => <p>value: {d.n}</p>}
      </QueryState>,
    );
    expect(screen.getByText("value: 1")).toBeInTheDocument();
  });

  it("renders the empty state when isEmpty matches, even for a successfully-resolved query", () => {
    render(
      <QueryState
        isLoading={false}
        data={[]}
        isError={false}
        error={null}
        refetch={vi.fn()}
        fetchStatus="idle"
        isEmpty={(rows: unknown[]) => rows.length === 0}
        emptyTitle="Nothing here yet."
      >
        {() => <p>content</p>}
      </QueryState>,
    );
    expect(screen.getByText("Nothing here yet.")).toBeInTheDocument();
  });
});
