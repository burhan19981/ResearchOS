import { useAnalysisRecords } from "@/api/hooks";
import { Card, CardBody } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryState } from "@/components/ui/QueryState";
import { StatusPill } from "@/components/ui/StatusPill";
import { SubNav } from "@/components/ui/SubNav";
import { formatDateTime, humanizeToken } from "@/lib/format";
import { useEffectiveProjectId } from "@/lib/useEffectiveProjectId";
import type { AnalysisRecordResponse } from "@/types/api";

/**
 * A `NOT_COMPARABLE` record's `result.reasons` are shown verbatim —
 * this page never attempts to reinterpret or "fix" a comparability
 * finding, and never converts a numeric comparison into a scientific
 * verdict such as "better"/"best"/"winner" (Dashboard V1 spec section
 * 16).
 */
export function AnalysisPage() {
  const projectId = useEffectiveProjectId();
  const query = useAnalysisRecords(projectId);

  return (
    <div>
      <PageHeader title="Analysis" description="Deterministic computations over Run/Metric evidence — never a scientific conclusion by itself." />
      <SubNav items={[{ label: "Analysis Records", to: "/dashboard/analysis", end: true }, { label: "Reviews & Claims", to: "/dashboard/analysis/reviews" }]} />
      <QueryState
        {...query}
        data={query.data}
        refetch={() => void query.refetch()}
        isEmpty={(rows) => rows.length === 0}
        emptyTitle="No analyses have been computed yet."
      >
        {(records) => (
          <div className="flex flex-col gap-3">
            {records.map((record) => (
              <AnalysisRecordCard key={record.id} record={record} />
            ))}
          </div>
        )}
      </QueryState>
    </div>
  );
}

function AnalysisRecordCard({ record }: { record: AnalysisRecordResponse }) {
  const notComparable = record.status === "not_comparable";
  const reasons = notComparable ? (record.result.reasons as string[] | undefined) ?? [] : [];

  return (
    <Card className={notComparable ? "border-status-warning/40" : undefined}>
      <CardBody>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-text-primary">{humanizeToken(record.method)}</span>
          <StatusPill status={record.status} />
          <span className="text-xs text-text-muted">v{record.version}</span>
          <span className="ml-auto text-xs text-text-muted">{formatDateTime(record.created_at)}</span>
        </div>

        {notComparable ? (
          <div>
            <p className="text-sm font-medium text-status-warning">Comparison unavailable</p>
            <ul className="mt-1 list-inside list-disc text-sm text-text-secondary">
              {reasons.map((reason, index) => (
                <li key={index}>{reason}</li>
              ))}
            </ul>
          </div>
        ) : (
          <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            {Object.entries(record.result)
              .filter(([, value]) => typeof value !== "object")
              .map(([key, value]) => (
                <div key={key}>
                  <dt className="text-[11px] uppercase tracking-wide text-text-muted">{humanizeToken(key)}</dt>
                  <dd className="text-text-primary">{String(value)}</dd>
                </div>
              ))}
          </dl>
        )}

        <p className="mt-2 text-[11px] text-text-muted">{record.inputs.length} input(s) used</p>
      </CardBody>
    </Card>
  );
}
