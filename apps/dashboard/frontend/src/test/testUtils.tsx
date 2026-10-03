import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { ProjectProvider } from "@/lib/ProjectContext";

/** A fresh, retry-disabled QueryClient per test so failed requests
 * resolve immediately instead of retrying and timing out the test. */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } },
  });
}

export function renderWithProviders(
  ui: ReactElement,
  { route = "/dashboard", queryClient = createTestQueryClient() }: { route?: string; queryClient?: QueryClient } = {},
) {
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <ProjectProvider>
          <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
        </ProjectProvider>
      </QueryClientProvider>,
    ),
  };
}

export function jsonResponse(body: unknown, init: { status?: number } = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json" },
  });
}
