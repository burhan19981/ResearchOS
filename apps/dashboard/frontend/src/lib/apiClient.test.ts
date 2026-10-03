import { afterEach, describe, expect, it, vi } from "vitest";
import { apiGet, apiPost, ApiError } from "./apiClient";

describe("apiClient", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("apiGet returns parsed JSON on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ hello: "world" }), { status: 200 })),
    );
    const result = await apiGet<{ hello: string }>("/health");
    expect(result).toEqual({ hello: "world" });
  });

  it("apiGet throws a structured ApiError on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "NotFoundError", detail: "Project 999 does not exist." }), { status: 404 }),
      ),
    );
    await expect(apiGet("/projects/999")).rejects.toMatchObject({
      status: 404,
      message: "Project 999 does not exist.",
    });
  });

  it("apiGet falls back to a generic message when the error body is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>502</html>", { status: 502 })));
    await expect(apiGet("/projects")).rejects.toBeInstanceOf(ApiError);
  });

  it("apiPost sends a JSON body with the Content-Type header set", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await apiPost("/projects/1/approvals/1/actions", { action: "approve" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ action: "approve" }));
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });
});
