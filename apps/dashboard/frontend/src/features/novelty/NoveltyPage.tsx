import { useNovelty } from "@/api/hooks";
import { Card, CardBody } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryState } from "@/components/ui/QueryState";
import { StatusPill } from "@/components/ui/StatusPill";
import { SubNav } from "@/components/ui/SubNav";
import { useEffectiveProjectId } from "@/lib/useEffectiveProjectId";
import type { NoveltyAssessmentResponse } from "@/types/api";

/**
 * Never presents `candidate_status` as a settled "Novelty confirmed"
 * claim — the status vocabulary is shown verbatim (CANDIDATE,
 * INSUFFICIENT_EVIDENCE, HUMAN_APPROVED, ...) via `StatusPill`, which
 * is the only place novelty status is rendered (Dashboard V1 spec
 * section 11).
 */
export function NoveltyPage() {
  const projectId = useEffectiveProjectId();
  const query = useNovelty(projectId);

  return (
    <div>
      <PageHeader title="Novelty Assessments" />
      <SubNav
        items={[
          { label: "Literature", to: "/dashboard/evidence" },
          { label: "Gaps", to: "/dashboard/evidence/gaps" },
          { label: "Novelty", to: "/dashboard/evidence/novelty" },
        ]}
      />
      <QueryState
        {...query}
        data={query.data}
        refetch={() => void query.refetch()}
        isEmpty={(items) => items.length === 0}
        emptyTitle="No novelty assessments have been recorded yet."
      >
        {(items) => (
          <div className="flex flex-col gap-3">
            {items.map((item) => (
              <NoveltyCard key={item.id} assessment={item} />
            ))}
          </div>
        )}
      </QueryState>
    </div>
  );
}

function NoveltyCard({ assessment }: { assessment: NoveltyAssessmentResponse }) {
  return (
    <Card>
      <CardBody>
        <div className="mb-2 flex items-center gap-2">
          <StatusPill status={assessment.candidate_status} />
          {assessment.confidence !== null ? (
            <span className="text-xs text-text-muted">Confidence: {Math.round(assessment.confidence * 100)}%</span>
          ) : null}
        </div>
        <p className="text-sm text-text-primary">{assessment.claim}</p>
        {assessment.novelty_risk ? (
          <p className="mt-1 text-xs text-text-secondary">Risk: {assessment.novelty_risk}</p>
        ) : null}
        {assessment.unresolved_questions ? (
          <p className="mt-1 text-xs text-status-warning">Unresolved: {assessment.unresolved_questions}</p>
        ) : null}
      </CardBody>
    </Card>
  );
}
