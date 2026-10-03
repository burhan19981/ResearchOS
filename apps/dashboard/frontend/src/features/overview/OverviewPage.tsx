import { FlaskConical, Layers, Lightbulb, Sparkles } from "lucide-react";
import { useOverview } from "@/api/hooks";
import { Card, CardBody } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryState } from "@/components/ui/QueryState";
import { StatusPill } from "@/components/ui/StatusPill";
import { humanizeToken } from "@/lib/format";
import { useEffectiveProjectId } from "@/lib/useEffectiveProjectId";
import { EmptyState } from "@/components/ui/States";
import type { OverviewCounts } from "@/types/api";

const STAT_LABELS: Record<keyof OverviewCounts, string> = {
  literature_items: "Literature Items",
  research_gaps: "Research Gaps",
  novelty_assessments: "Novelty Assessments",
  research_questions: "Research Questions",
  contribution_candidates: "Contributions",
  experiments: "Experiments",
  runs: "Runs",
  metrics: "Metrics",
  analysis_records: "Analysis Records",
  scientific_claims: "Scientific Claims",
  scientific_reviews: "Scientific Reviews",
  pending_approvals: "Pending Approvals",
};

const STAT_EMPTY_COPY: Partial<Record<keyof OverviewCounts, string>> = {
  literature_items: "No literature items have been collected yet.",
  research_gaps: "No research gaps have been recorded yet.",
  experiments: "No experiments have been created yet.",
  runs: "No runs have been executed yet.",
  analysis_records: "No analyses have been computed yet.",
  scientific_reviews: "No scientific reviews exist yet.",
  pending_approvals: "Nothing is waiting for approval.",
};

export function OverviewPage() {
  const projectId = useEffectiveProjectId();
  const query = useOverview(projectId);

  if (projectId === null) {
    return (
      <EmptyState
        icon={<Layers size={28} aria-hidden="true" />}
        title="No project selected"
        description="Choose a project from the selector in the top bar to see its overview."
      />
    );
  }

  return (
    <QueryState {...query} data={query.data} refetch={() => void query.refetch()}>
      {(overview) => (
        <div>
          <PageHeader
            title={overview.project.title}
            description={overview.project.description ?? undefined}
            actions={
              <div className="flex items-center gap-2">
                <StatusPill status={overview.project.status} />
                <StatusPill status={overview.current_stage} label={humanizeToken(overview.current_stage)} />
              </div>
            }
          />

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {(Object.keys(STAT_LABELS) as (keyof OverviewCounts)[]).map((key) => {
              const value = overview.counts[key];
              return (
                <Card key={key}>
                  <CardBody>
                    <p className="text-2xl font-semibold text-text-primary">{value}</p>
                    <p className="mt-1 text-xs text-text-secondary">{STAT_LABELS[key]}</p>
                    {value === 0 && STAT_EMPTY_COPY[key] ? (
                      <p className="mt-1 text-[11px] text-text-muted">{STAT_EMPTY_COPY[key]}</p>
                    ) : null}
                  </CardBody>
                </Card>
              );
            })}
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            <Card>
              <CardBody className="flex items-center gap-3">
                <Lightbulb size={20} className="text-accent" aria-hidden="true" />
                <div>
                  <p className="text-sm font-medium text-text-primary">Research Pipeline</p>
                  <p className="text-xs text-text-secondary">
                    Currently at <strong className="text-text-primary">{humanizeToken(overview.current_stage)}</strong>. See
                    the full pipeline for allowed next steps.
                  </p>
                </div>
              </CardBody>
            </Card>
            <Card>
              <CardBody className="flex items-center gap-3">
                {overview.counts.pending_approvals > 0 ? (
                  <Sparkles size={20} className="text-status-warning" aria-hidden="true" />
                ) : (
                  <FlaskConical size={20} className="text-status-success" aria-hidden="true" />
                )}
                <div>
                  <p className="text-sm font-medium text-text-primary">
                    {overview.counts.pending_approvals} pending approval
                    {overview.counts.pending_approvals === 1 ? "" : "s"}
                  </p>
                  <p className="text-xs text-text-secondary">
                    {overview.counts.pending_approvals > 0
                      ? "Review them in the Approval Center."
                      : "Nothing currently requires a human decision."}
                  </p>
                </div>
              </CardBody>
            </Card>
          </div>
        </div>
      )}
    </QueryState>
  );
}
