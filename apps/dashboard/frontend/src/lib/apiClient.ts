import type { ApiErrorBody } from "../types/api";

/**
 * The single place the frontend talks HTTP to the FastAPI backend.
 * Never touches SQLite/SQLAlchemy directly — every piece of data this
 * app shows came from a `fetch()` call through here.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody | null;

  constructor(status: number, body: ApiErrorBody | null, fallbackMessage: string) {
    super(body?.detail ?? fallbackMessage);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // Response was not JSON (e.g. a network-layer/proxy error page) —
      // ApiError falls back to a generic message rather than throwing
      // a second, more confusing parse error.
    }
    throw new ApiError(response.status, body, `Request to ${path} failed with status ${response.status}.`);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path, { method: "GET" });
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}
