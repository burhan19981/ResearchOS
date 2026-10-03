import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

/**
 * Central query-key builders — every project-scoped key includes the
 * project id, so switching projects never serves another project's
 * cached data and invalidation after an approval mutation only needs
 * to target the affected project's keys (Dashboard V1 spec section 25).
 */
export const queryKeys = {
  projects: () => ["projects"] as const,
  project: (projectId: number) => ["projects", projectId] as const,
  overview: (projectId: number) => ["projects", projectId, "overview"] as const,
  pipeline: (projectId: number) => ["projects", projectId, "pipeline"] as const,
  literature: (projectId: number) => ["projects", projectId, "literature"] as const,
  gaps: (projectId: number) => ["projects", projectId, "gaps"] as const,
  novelty: (projectId: number) => ["projects", projectId, "novelty"] as const,
  planning: (projectId: number) => ["projects", projectId, "planning"] as const,
  experiments: (projectId: number) => ["projects", projectId, "experiments", "list"] as const,
  experiment: (projectId: number, experimentId: number) =>
    ["projects", projectId, "experiments", "detail", experimentId] as const,
  // "list"/"detail" discriminators are load-bearing, not decorative: a
  // list key filtered by experimentId (e.g. ["projects", 1, "runs",
  // "list", 1]) and a single-run detail key (["projects", 1, "runs",
  // "detail", 1]) must never collide even when experimentId === runId
  // numerically — they did before this discriminator existed, and
  // TanStack Query silently served the cached *array* from the list
  // query as if it were the single Run the detail page expected,
  // crashing RunDetailPage on `run.metrics.length`. Caught by the
  // Playwright e2e smoke test, not by any unit/component test.
  runs: (projectId: number, experimentId?: number | null) =>
    ["projects", projectId, "runs", "list", experimentId ?? null] as const,
  run: (projectId: number, runId: number) => ["projects", projectId, "runs", "detail", runId] as const,
  analysis: (projectId: number) => ["projects", projectId, "analysis"] as const,
  reviews: (projectId: number) => ["projects", projectId, "reviews"] as const,
  approvals: (projectId: number) => ["projects", projectId, "approvals"] as const,
  audit: (projectId: number) => ["projects", projectId, "audit"] as const,
  health: () => ["health"] as const,
};
