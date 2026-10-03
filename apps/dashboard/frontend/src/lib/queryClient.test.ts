import { describe, expect, it } from "vitest";
import { queryKeys } from "./queryClient";

describe("queryKeys", () => {
  it("never produces the same key for a filtered run list and a single run detail, even when experimentId === runId", () => {
    // Regression test: TanStack Query caches by exact key equality.
    // Before this fix, queryKeys.runs(1, 1) and queryKeys.run(1, 1)
    // were both ["projects", 1, "runs", 1] — identical — so the
    // single-run detail query silently received the cached *array*
    // from the list query, crashing RunDetailPage on
    // `run.metrics.length` (`run` was actually an array). Caught live
    // by the Playwright e2e smoke test, not by any earlier unit test.
    const listKey = queryKeys.runs(1, 1);
    const detailKey = queryKeys.run(1, 1);
    expect(listKey).not.toEqual(detailKey);
    expect(JSON.stringify(listKey)).not.toBe(JSON.stringify(detailKey));
  });

  it("keeps experiment list and experiment detail keys distinct under the same collision scenario", () => {
    const listKey = queryKeys.experiments(1);
    const detailKey = queryKeys.experiment(1, 1);
    expect(JSON.stringify(listKey)).not.toBe(JSON.stringify(detailKey));
  });

  it("still scopes every project-level key so a different project never shares a key", () => {
    expect(queryKeys.run(1, 5)).not.toEqual(queryKeys.run(2, 5));
    expect(queryKeys.runs(1, 5)).not.toEqual(queryKeys.runs(2, 5));
  });
});
