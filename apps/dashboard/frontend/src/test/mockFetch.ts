import { vi } from "vitest";
import { jsonResponse } from "./testUtils";

/**
 * A tiny path-matching fetch mock: each entry's key is matched against
 * the request URL's pathname+search using `.includes()`, in
 * declaration order — the first match wins. Keeps component tests
 * readable without pulling in a full HTTP-mocking library for a V1
 * dashboard's modest test surface.
 */
export function mockFetchRoutes(routes: Array<[string, unknown, number?]>) {
  // Longest matcher wins, regardless of declaration order — otherwise
  // a short matcher like "/api/v1/projects" silently swallows a more
  // specific request like "/api/v1/projects/1" (a real bug this
  // caught: the singular-project endpoint was matching the
  // project-list route and getting an array back where an object was
  // expected).
  const sorted = [...routes].sort((a, b) => b[0].length - a[0].length);
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    for (const [matcher, body, status] of sorted) {
      if (url.includes(matcher)) {
        return jsonResponse(body, { status: status ?? 200 });
      }
    }
    throw new Error(`mockFetchRoutes: no route configured for ${url}`);
  });
}
