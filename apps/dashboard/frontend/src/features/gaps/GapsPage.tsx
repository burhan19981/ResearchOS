import { useGaps } from "@/api/hooks";
import { Card, CardBody } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryState } from "@/components/ui/QueryState";
import { StatusPill } from "@/components/ui/StatusPill";
import { SubNav } from "@/components/ui/SubNav";
import { formatDateTime } from "@/lib/format";
import { useEffectiveProjectId } from "@/lib/useEffectiveProjectId";
import type { ResearchGapResponse } from "@/types/api";

export function GapsPage() {
  const projectId = useEffectiveProjectId();
  const query = useGaps(projectId);

  return (
    <div>
      <PageHeader title="Research Gaps" />
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
        isEmpty={(gaps) => gaps.length === 0}
        emptyTitle="No research gaps have been recorded yet."
      >
        {(gaps) => (
          <div className="flex flex-col gap-3">
            {gaps.map((gap) => (
              <GapCard key={gap.id} gap={gap} />
            ))}
          </div>
        )}
      </QueryState>
    </div>
  );
}

function GapCard({ gap }: { gap: ResearchGapResponse }) {
  return (
    <Card>
      <CardBody>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <StatusPill status={gap.status} />
          {gap.gap_type ? <span className="text-xs text-text-muted">{gap.gap_type}</span> : null}
          <span className="text-xs text-text-muted">
            {gap.evidence_count} supporting evidence link{gap.evidence_count === 1 ? "" : "s"}
          </span>
        </div>
        <p className="text-sm text-text-primary">{gap.statement}</p>
        {gap.affected_research_area ? (
          <p className="mt-1 text-xs text-text-secondary">Area: {gap.affected_research_area}</p>
        ) : null}
        <p className="mt-2 text-[11px] text-text-muted">Updated {formatDateTime(gap.updated_at)}</p>
      </CardBody>
    </Card>
  );
}
