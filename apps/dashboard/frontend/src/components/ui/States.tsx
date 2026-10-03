import { AlertCircle, Inbox, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "@/lib/apiClient";

/**
 * The three states every data-driven view in this app must handle
 * explicitly (Dashboard V1 spec sections 10/22/25/31): loading, empty,
 * and error — never a blank screen, never a raw stack trace.
 */

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-text-muted" role="status" aria-live="polite">
      <Loader2 size={16} className="animate-spin" aria-hidden="true" />
      {label}
    </div>
  );
}

export function EmptyState({ icon, title, description }: { icon?: ReactNode; title: string; description?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center text-text-secondary">
      <div className="text-text-muted">{icon ?? <Inbox size={28} aria-hidden="true" />}</div>
      <p className="text-sm font-medium text-text-primary">{title}</p>
      {description ? <p className="max-w-sm text-xs text-text-muted">{description}</p> : null}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof ApiError ? error.message : error instanceof Error ? error.message : "An unexpected error occurred.";
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center" role="alert">
      <AlertCircle size={28} className="text-status-danger" aria-hidden="true" />
      <p className="text-sm font-medium text-text-primary">Something went wrong loading this data.</p>
      <p className="max-w-sm text-xs text-text-muted">{message}</p>
      {retry ? (
        <button
          type="button"
          onClick={retry}
          className="mt-2 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-2"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}
