import { Link } from "react-router-dom";
import { useExperiments } from "@/api/hooks";
import { DataTable } from "@/components/ui/Table";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryState } from "@/components/ui/QueryState";
import { StatusPill } from "@/components/ui/StatusPill";
import { formatDateTime } from "@/lib/format";
import { useEffectiveProjectId } from "@/lib/useEffectiveProjectId";
import type { ExperimentResponse } from "@/types/api";

export function ExperimentsPage() {
  const projectId = useEffectiveProjectId();
  const query = useExperiments(projectId);

  return (
    <div>
      <PageHeader title="Experiments" description="Experiments and the Runs executed under them." />
      <QueryState
        {...query}
        data={query.data}
        refetch={() => void query.refetch()}
        isEmpty={(rows) => rows.length === 0}
        emptyTitle="No experiments have been created yet."
      >
        {(experiments) => <ExperimentsTable experiments={experiments} />}
      </QueryState>
    </div>
  );
}

function ExperimentsTable({ experiments }: { experiments: ExperimentResponse[] }) {
  return (
    <DataTable
      caption="Experiments for the selected project"
      rows={experiments}
      rowKey={(row) => row.id}
      columns={[
        {
          header: "Name",
          render: (row) => (
            <Link to={`/dashboard/experiments/${row.id}`} className="font-medium text-accent hover:underline">
              {row.name}
            </Link>
          ),
        },
        { header: "Status", render: (row) => <StatusPill status={row.status} /> },
        { header: "Runs", render: (row) => row.run_count },
        { header: "Specifications", render: (row) => row.specification_count },
        { header: "Hardware", render: (row) => row.hardware ?? "—" },
        { header: "Created", render: (row) => formatDateTime(row.created_at) },
      ]}
    />
  );
}
