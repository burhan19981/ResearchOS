import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { useExperiment, useRuns } from "@/api/hooks";
import { Card, CardBody } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryState } from "@/components/ui/QueryState";
import { StatusPill } from "@/components/ui/StatusPill";
import { DataTable } from "@/components/ui/Table";
import { formatDateTime, formatDuration } from "@/lib/format";
import { useEffectiveProjectId } from "@/lib/useEffectiveProjectId";
import type { ExperimentResponse, RunResponse } from "@/types/api";

export function ExperimentDetailPage() {
  const projectId = useEffectiveProjectId();
  const params = useParams<{ experimentId: string }>();
  const experimentId = params.experimentId ? Number(params.experimentId) : null;
  const experimentQuery = useExperiment(projectId, experimentId);
  const runsQuery = useRuns(projectId, experimentId ?? undefined);

  return (
    <div>
      <Link to="/dashboard/experiments" className="mb-3 inline-flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary">
        <ArrowLeft size={13} aria-hidden="true" /> Back to Experiments
      </Link>
      <QueryState {...experimentQuery} data={experimentQuery.data} refetch={() => void experimentQuery.refetch()}>
        {(experiment) => <ExperimentSummary experiment={experiment} />}
      </QueryState>

      <div className="mt-6">
        <h2 className="mb-3 text-sm font-semibold text-text-primary">Runs</h2>
        <QueryState
          {...runsQuery}
          data={runsQuery.data}
          refetch={() => void runsQuery.refetch()}
          isEmpty={(rows) => rows.length === 0}
          emptyTitle="No runs have been executed for this experiment yet."
        >
          {(runs) => <RunsTable runs={runs} />}
        </QueryState>
      </div>
    </div>
  );
}

function ExperimentSummary({ experiment }: { experiment: ExperimentResponse }) {
  return (
    <div>
      <PageHeader title={experiment.name} description={experiment.description ?? undefined} actions={<StatusPill status={experiment.status} />} />
      <Card>
        <CardBody className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Field label="Code version" value={experiment.code_version} />
          <Field label="Dataset version" value={experiment.dataset_version} />
          <Field label="Random seed" value={experiment.random_seed?.toString() ?? null} />
          <Field label="Hardware" value={experiment.hardware} />
          <Field label="Started" value={formatDateTime(experiment.started_at)} />
          <Field label="Completed" value={formatDateTime(experiment.completed_at)} />
          <Field label="Run count" value={String(experiment.run_count)} />
          <Field label="Specifications" value={String(experiment.specification_count)} />
        </CardBody>
      </Card>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-text-muted">{label}</p>
      <p className="text-text-primary">{value ?? "—"}</p>
    </div>
  );
}

function RunsTable({ runs }: { runs: RunResponse[] }) {
  return (
    <DataTable
      caption="Runs for this experiment"
      rows={runs}
      rowKey={(row) => row.id}
      columns={[
        {
          header: "Run",
          render: (row) => (
            <Link to={`/dashboard/experiments/runs/${row.id}`} className="font-medium text-accent hover:underline">
              #{row.id}
            </Link>
          ),
        },
        { header: "Status", render: (row) => <StatusPill status={row.status} /> },
        { header: "Duration", render: (row) => formatDuration(row.duration_seconds) },
        { header: "Exit code", render: (row) => row.exit_code ?? "—" },
        { header: "Config hash", render: (row) => (row.configuration_hash ? row.configuration_hash.slice(0, 10) : "—") },
        { header: "Created", render: (row) => formatDateTime(row.created_at) },
      ]}
    />
  );
}
