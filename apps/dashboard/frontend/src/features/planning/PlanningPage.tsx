import { usePlanning } from "@/api/hooks";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryState } from "@/components/ui/QueryState";
import { StatusPill } from "@/components/ui/StatusPill";
import { EmptyState } from "@/components/ui/States";
import { useEffectiveProjectId } from "@/lib/useEffectiveProjectId";
import type { PlanningResponse } from "@/types/api";

/**
 * Visualizes the existing traceability chain Research Gap -> Research
 * Question -> Contribution -> Methodology -> Dataset Requirements ->
 * Experimental Design -> Experiment Specification — every list here
 * is a project-scoped read of an already-persisted table, never a
 * computed/inferred relationship (Dashboard V1 spec section 12).
 */
export function PlanningPage() {
  const projectId = useEffectiveProjectId();
  const query = usePlanning(projectId);

  return (
    <div>
      <PageHeader title="Research Planning" description="The traceability chain from research questions through to experiment specifications." />
      <QueryState {...query} data={query.data} refetch={() => void query.refetch()}>
        {(planning) => <PlanningChain planning={planning} />}
      </QueryState>
    </div>
  );
}

function PlanningChain({ planning }: { planning: PlanningResponse }) {
  const sections: { title: string; count: number; render: () => React.ReactNode }[] = [
    {
      title: "Research Questions",
      count: planning.research_questions.length,
      render: () => (
        <ul className="flex flex-col gap-2">
          {planning.research_questions.map((q) => (
            <li key={q.id} className="flex items-center justify-between gap-2 text-sm">
              <span className="text-text-primary">{q.question}</span>
              <StatusPill status={q.planning_status} />
            </li>
          ))}
        </ul>
      ),
    },
    {
      title: "Contribution Candidates",
      count: planning.contribution_candidates.length,
      render: () => (
        <ul className="flex flex-col gap-2">
          {planning.contribution_candidates.map((c) => (
            <li key={c.id} className="text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-text-primary">{c.title}</span>
                <StatusPill status={c.planning_status} />
              </div>
              <p className="text-xs text-text-secondary">{c.description}</p>
              {c.cited_research_question_ids.length > 0 ? (
                <p className="mt-0.5 text-[11px] text-text-muted">
                  Cites question(s): {c.cited_research_question_ids.join(", ")}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      ),
    },
    {
      title: "Methodology Plans",
      count: planning.methodology_plans.length,
      render: () => (
        <ul className="flex flex-col gap-2">
          {planning.methodology_plans.map((m) => (
            <li key={m.id} className="text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="text-text-primary">v{m.version}</span>
                <StatusPill status={m.planning_status} />
              </div>
              <p className="text-xs text-text-secondary">{m.description}</p>
            </li>
          ))}
        </ul>
      ),
    },
    {
      title: "Dataset Requirements",
      count: planning.dataset_requirements.length,
      render: () => (
        <ul className="flex flex-col gap-2">
          {planning.dataset_requirements.map((d) => (
            <li key={d.id} className="text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="text-text-primary">Requirement #{d.id}</span>
                <StatusPill status={d.planning_status} />
              </div>
              <p className="text-xs text-text-secondary">{d.required_characteristics ?? "—"}</p>
            </li>
          ))}
        </ul>
      ),
    },
    {
      title: "Experimental Designs",
      count: planning.experimental_designs.length,
      render: () => (
        <ul className="flex flex-col gap-2">
          {planning.experimental_designs.map((e) => (
            <li key={e.id} className="text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="text-text-primary">v{e.version}</span>
                <StatusPill status={e.planning_status} />
              </div>
              <p className="text-xs text-text-secondary">{e.proposed_method ?? "—"}</p>
            </li>
          ))}
        </ul>
      ),
    },
    {
      title: "Experiment Specifications",
      count: planning.experiment_specifications.length,
      render: () => (
        <ul className="flex flex-col gap-2">
          {planning.experiment_specifications.map((s) => (
            <li key={s.id} className="text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="text-text-primary">v{s.version}</span>
                <StatusPill status={s.planning_status} />
              </div>
              <p className="text-xs text-text-secondary">{s.description ?? "—"}</p>
            </li>
          ))}
        </ul>
      ),
    },
  ];

  const totalCount = sections.reduce((sum, s) => sum + s.count, 0);
  if (totalCount === 0) {
    return <EmptyState title="No planning artifacts exist yet." description="Research questions, contributions, and downstream planning artifacts will appear here once created." />;
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {sections.map((section) => (
        <Card key={section.title}>
          <CardHeader>
            <CardTitle>
              {section.title} ({section.count})
            </CardTitle>
          </CardHeader>
          <CardBody>{section.count > 0 ? section.render() : <p className="text-sm text-text-muted">None yet.</p>}</CardBody>
        </Card>
      ))}
    </div>
  );
}
