import { useAuditEvents } from "@/api/hooks";
import { DataTable } from "@/components/ui/Table";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryState } from "@/components/ui/QueryState";
import { formatDateTime } from "@/lib/format";
import { useEffectiveProjectId } from "@/lib/useEffectiveProjectId";
import type { AuditEventResponse } from "@/types/api";

/** Strictly read-only — this page issues only `GET` requests
 * (Dashboard V1 spec section 19). */
export function AuditPage() {
  const projectId = useEffectiveProjectId();
  const query = useAuditEvents(projectId);

  return (
    <div>
      <PageHeader title="Audit Log" description="Chronological, read-only record of every state change ResearchOS itself made for this project." />
      <QueryState
        {...query}
        data={query.data}
        refetch={() => void query.refetch()}
        isEmpty={(rows) => rows.length === 0}
        emptyTitle="No audit events have been recorded yet."
      >
        {(events) => <AuditTable events={events} />}
      </QueryState>
    </div>
  );
}

function AuditTable({ events }: { events: AuditEventResponse[] }) {
  const reversed = [...events].reverse();
  return (
    <DataTable
      caption="Audit events for the selected project, most recent first"
      rows={reversed}
      rowKey={(row) => row.id}
      columns={[
        { header: "Time", render: (row) => formatDateTime(row.created_at) },
        { header: "Event", render: (row) => <code className="text-xs">{row.event_type}</code> },
        { header: "Actor", render: (row) => row.actor },
        { header: "Description", render: (row) => row.description ?? "—" },
      ]}
    />
  );
}
