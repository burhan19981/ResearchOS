import type { ReactNode } from "react";
import { EmptyState, ErrorState, LoadingState } from "./States";

interface QueryStateProps<T> {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  refetch: () => void;
  /** TanStack Query's own `fetchStatus` — every call site already
   * spreads the full `useQuery()` result (`<QueryState {...query} .../>`),
   * so this flows through automatically without any page-level change. */
  fetchStatus?: "fetching" | "paused" | "idle";
  isEmpty?: (data: T) => boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  children: (data: T) => ReactNode;
}

/** The one place loading/error/empty/success branching happens for a
 * single TanStack Query result — every feature page uses this instead
 * of repeating the same four-way branch (Dashboard V1 spec section
 * 31). */
export function QueryState<T>({
  isLoading,
  isError,
  error,
  data,
  refetch,
  fetchStatus,
  isEmpty,
  emptyTitle,
  emptyDescription,
  children,
}: QueryStateProps<T>) {
  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState error={error} retry={refetch} />;
  if (data === undefined) {
    // A *disabled* query (every project-scoped hook passes
    // `enabled: projectId !== null`) never transitions out of
    // TanStack Query's "pending" status on its own — it just sits
    // forever with `data === undefined` and `isLoading === false`,
    // since no fetch was ever attempted. `fetchStatus === "idle"` is
    // exactly that case (as opposed to "fetching"/"paused", which
    // mean a request really is in flight) — rendering an eternal
    // spinner here, instead of recognizing "there is nothing to load
    // yet," was the reported "Dashboard pages stuck in Loading" bug
    // for every page except Overview (which had its own separate,
    // manual `projectId === null` guard the other 11 pages lacked).
    if (fetchStatus === "idle") {
      return (
        <EmptyState
          title="No project selected"
          description="Choose a project from the selector in the top bar to load this page."
        />
      );
    }
    return <LoadingState />;
  }
  if (isEmpty?.(data)) {
    return <EmptyState title={emptyTitle ?? "Nothing here yet."} description={emptyDescription} />;
  }
  return <>{children(data)}</>;
}
