import { useEffect, useId, useState } from "react";
import { useActOnApproval } from "@/api/hooks";
import { ApiError } from "@/lib/apiClient";
import { formatDateTime, humanizeToken } from "@/lib/format";
import { StatusPill } from "@/components/ui/StatusPill";
import type { ApprovalAction, ApprovalResponse } from "@/types/api";

const ACTIONS: { value: ApprovalAction; label: string; tone: string }[] = [
  { value: "approve", label: "Approve", tone: "bg-status-success hover:opacity-90" },
  { value: "request_changes", label: "Request Changes", tone: "bg-status-warning hover:opacity-90" },
  { value: "reject", label: "Reject", tone: "bg-status-danger hover:opacity-90" },
];

/**
 * Requires an explicit action before anything is sent — there is no
 * default/pre-selected decision. On success it shows the resulting
 * persisted state read back from the server, never an assumed
 * outcome (Dashboard V1 spec section 18, steps 1-6).
 */
export function ApprovalActionDialog({
  approval,
  projectId,
  onClose,
}: {
  approval: ApprovalResponse;
  projectId: number;
  onClose: () => void;
}) {
  const titleId = useId();
  const [selectedAction, setSelectedAction] = useState<ApprovalAction | null>(null);
  const [comment, setComment] = useState("");
  const mutation = useActOnApproval(projectId);

  const handleSubmit = () => {
    if (!selectedAction) return;
    mutation.mutate({ approvalId: approval.id, body: { action: selectedAction, comment: comment || null } });
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4" role="presentation" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-md rounded-lg border border-border bg-surface-1 p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id={titleId} className="text-sm font-semibold text-text-primary">
          {humanizeToken(approval.entity_type)}
          {approval.entity_id !== null ? ` #${approval.entity_id}` : ""}
        </h2>
        <p className="mt-1 text-xs text-text-muted">
          Stage: <code>{approval.stage}</code> · Requested {formatDateTime(approval.requested_at)}
        </p>

        {mutation.isSuccess ? (
          <div className="mt-4">
            <p className="text-sm font-medium text-status-success">Decision recorded.</p>
            <div className="mt-2 flex items-center gap-2 text-sm">
              <span className="text-text-secondary">Resulting status:</span>
              <StatusPill status={mutation.data.entity_status} />
            </div>
            <button
              type="button"
              onClick={onClose}
              className="mt-4 w-full rounded-md border border-border px-3 py-2 text-sm font-medium text-text-primary hover:bg-surface-2"
            >
              Close
            </button>
          </div>
        ) : (
          <div className="mt-4">
            <fieldset>
              <legend className="mb-2 text-xs font-medium text-text-secondary">Decision</legend>
              <div className="flex gap-2">
                {ACTIONS.map((action) => (
                  <label
                    key={action.value}
                    className={`flex-1 cursor-pointer rounded-md border px-2 py-2 text-center text-xs font-medium transition-colors ${
                      selectedAction === action.value
                        ? "border-accent bg-accent/15 text-text-primary"
                        : "border-border text-text-secondary hover:bg-surface-2"
                    }`}
                  >
                    <input
                      type="radio"
                      name="approval-action"
                      value={action.value}
                      className="sr-only"
                      checked={selectedAction === action.value}
                      onChange={() => setSelectedAction(action.value)}
                    />
                    {action.label}
                  </label>
                ))}
              </div>
            </fieldset>

            <label htmlFor="approval-comment" className="mb-1 mt-3 block text-xs font-medium text-text-secondary">
              Comment (optional)
            </label>
            <textarea
              id="approval-comment"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              rows={3}
              className="w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-primary placeholder:text-text-muted"
              placeholder="Add context for this decision…"
            />

            {mutation.isError ? (
              <p role="alert" className="mt-2 text-xs text-status-danger">
                {mutation.error instanceof ApiError ? mutation.error.message : "The decision could not be recorded."}
              </p>
            ) : null}

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-md border border-border px-3 py-2 text-sm font-medium text-text-primary hover:bg-surface-2"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!selectedAction || mutation.isPending}
                className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {mutation.isPending ? "Submitting…" : "Submit Decision"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
