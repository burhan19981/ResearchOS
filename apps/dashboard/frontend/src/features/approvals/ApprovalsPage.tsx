import { useState } from "react";
import { useApprovals } from "@/api/hooks";
import { Card, CardBody } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryState } from "@/components/ui/QueryState";
import { StatusPill } from "@/components/ui/StatusPill";
import { formatDateTime, humanizeToken } from "@/lib/format";
import { useEffectiveProjectId } from "@/lib/useEffectiveProjectId";
import type { ApprovalResponse } from "@/types/api";
import { ApprovalActionDialog } from "./ApprovalActionDialog";

/**
 * The Approval Center. Every decision made here goes through
 * `POST /approvals/{id}/actions`, which dispatches to the exactly one
 * existing domain approve/reject/request-changes function — there is
 * no client-side approval state, and no field here can assert
 * `is_human=true` or otherwise self-authorize (Dashboard V1 spec
 * section 18).
 */
export function ApprovalsPage() {
  const projectId = useEffectiveProjectId();
  const query = useApprovals(projectId);
  const [activeApproval, setActiveApproval] = useState<ApprovalResponse | null>(null);

  const pending = (query.data ?? []).filter((a) => a.decision === "pending");
  const decided = (query.data ?? []).filter((a) => a.decision !== "pending");

  return (
    <div>
      <PageHeader title="Approval Center" description="Every decision here is recorded through ResearchOS's real, existing approval mechanism." />
      <QueryState {...query} data={query.data} refetch={() => void query.refetch()} isEmpty={(rows) => rows.length === 0} emptyTitle="No approvals exist for this project yet.">
        {() => (
          <div className="flex flex-col gap-6">
            <section>
              <h2 className="mb-3 text-sm font-semibold text-text-primary">Pending ({pending.length})</h2>
              {pending.length === 0 ? (
                <p className="text-sm text-text-muted">Nothing is currently waiting for a decision.</p>
              ) : (
                <div className="flex flex-col gap-2">
                  {pending.map((approval) => (
                    <ApprovalRow key={approval.id} approval={approval} onAct={() => setActiveApproval(approval)} />
                  ))}
                </div>
              )}
            </section>

            {decided.length > 0 ? (
              <section>
                <h2 className="mb-3 text-sm font-semibold text-text-primary">Decided ({decided.length})</h2>
                <div className="flex flex-col gap-2">
                  {decided.map((approval) => (
                    <ApprovalRow key={approval.id} approval={approval} />
                  ))}
                </div>
              </section>
            ) : null}
          </div>
        )}
      </QueryState>

      {activeApproval && projectId !== null ? (
        <ApprovalActionDialog
          approval={activeApproval}
          projectId={projectId}
          onClose={() => setActiveApproval(null)}
        />
      ) : null}
    </div>
  );
}

function ApprovalRow({ approval, onAct }: { approval: ApprovalResponse; onAct?: () => void }) {
  return (
    <Card>
      <CardBody className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-text-primary">{humanizeToken(approval.entity_type)}</span>
            {approval.entity_id !== null ? <span className="text-xs text-text-muted">#{approval.entity_id}</span> : null}
            <StatusPill status={approval.decision} />
          </div>
          <p className="mt-0.5 text-xs text-text-muted">
            Requested {formatDateTime(approval.requested_at)}
            {approval.decided_at ? ` · Decided ${formatDateTime(approval.decided_at)}` : ""}
          </p>
          {approval.comment ? <p className="mt-1 text-xs text-text-secondary">“{approval.comment}”</p> : null}
        </div>
        {onAct ? (
          <button
            type="button"
            onClick={onAct}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
          >
            Review
          </button>
        ) : null}
      </CardBody>
    </Card>
  );
}
