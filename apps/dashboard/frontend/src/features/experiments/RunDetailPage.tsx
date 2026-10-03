import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { useRun } from "@/api/hooks";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryState } from "@/components/ui/QueryState";
import { StatusPill } from "@/components/ui/StatusPill";
import { DataTable } from "@/components/ui/Table";
import { formatBytes, formatDateTime, formatDuration, formatNumber } from "@/lib/format";
import { useEffectiveProjectId } from "@/lib/useEffectiveProjectId";
import type { RunResponse } from "@/types/api";

/**
 * Every field here is read verbatim from the existing `Run` lifecycle
 * — no new execution status is invented, and metrics are shown as
 * plain values/tables, never labeled "best"/"winner" (Dashboard V1
 * spec sections 14-15).
 */
export function RunDetailPage() {
  const projectId = useEffectiveProjectId();
  const params = useParams<{ runId: string }>();
  const runId = params.runId ? Number(params.runId) : null;
  const query = useRun(projectId, runId);

  return (
    <div>
      <Link to="/dashboard/experiments" className="mb-3 inline-flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary">
        <ArrowLeft size={13} aria-hidden="true" /> Back to Experiments
      </Link>
      <QueryState {...query} data={query.data} refetch={() => void query.refetch()}>
        {(run) => <RunDetail run={run} />}
      </QueryState>
    </div>
  );
}

function RunDetail({ run }: { run: RunResponse }) {
  return (
    <div>
      <PageHeader title={`Run #${run.id}`} actions={<StatusPill status={run.status} />} />

      <Card>
        <CardBody className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Field label="Execution backend" value={run.execution_backend} />
          <Field label="Duration" value={formatDuration(run.duration_seconds)} />
          <Field label="Exit code" value={run.exit_code?.toString() ?? null} />
          <Field label="Seed" value={run.seed?.toString() ?? null} />
          <Field label="Started" value={formatDateTime(run.started_at)} />
          <Field label="Finished" value={formatDateTime(run.finished_at)} />
          <Field label="Timeout (s)" value={String(run.timeout_seconds)} />
          <Field label="Working tree clean" value={run.working_tree_clean === null ? null : run.working_tree_clean ? "Yes" : "No"} />
          <Field label="Configuration hash" value={run.configuration_hash} />
          <Field label="Dataset fingerprint" value={run.dataset_fingerprint} />
          <Field label="Code commit" value={run.code_commit} />
          <Field label="Code branch" value={run.code_branch} />
        </CardBody>
      </Card>

      {run.failure_reason ? (
        <Card className="mt-4 border-status-danger/40">
          <CardHeader>
            <CardTitle>Failure Reason</CardTitle>
          </CardHeader>
          <CardBody>
            <p className="whitespace-pre-wrap text-sm text-status-danger">{run.failure_reason}</p>
          </CardBody>
        </Card>
      ) : null}

      {run.environment ? (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Environment</CardTitle>
          </CardHeader>
          <CardBody className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Field label="OS" value={[run.environment.os_name, run.environment.os_version].filter(Boolean).join(" ") || null} />
            <Field label="Architecture" value={run.environment.architecture} />
            <Field label="Python" value={run.environment.python_version} />
            <Field label="PyTorch" value={run.environment.pytorch_version} />
            <Field label="CUDA" value={run.environment.cuda_version} />
            <Field label="GPU" value={run.environment.gpu_name} />
            <Field label="CPU" value={run.environment.cpu_model} />
            <Field label="CPU count" value={run.environment.cpu_count?.toString() ?? null} />
            <Field label="Memory" value={formatBytes(run.environment.total_memory_bytes)} />
            <Field label="ResearchOS version" value={run.environment.researchos_version} />
          </CardBody>
        </Card>
      ) : null}

      <div className="mt-4">
        <h2 className="mb-2 text-sm font-semibold text-text-primary">Metrics ({run.metrics.length})</h2>
        {run.metrics.length === 0 ? (
          <p className="text-sm text-text-muted">No metrics have been recorded for this run.</p>
        ) : (
          <DataTable
            caption="Metrics recorded for this run"
            rows={run.metrics}
            rowKey={(row) => row.id}
            columns={[
              { header: "Name", render: (row) => row.name },
              { header: "Value", render: (row) => formatNumber(row.value) },
              { header: "Unit", render: (row) => row.unit ?? "—" },
              { header: "Split", render: (row) => row.split ?? "—" },
              { header: "Aggregation", render: (row) => row.aggregation ?? "—" },
              { header: "Source", render: (row) => row.source ?? "—" },
            ]}
          />
        )}
      </div>

      <div className="mt-4">
        <h2 className="mb-2 text-sm font-semibold text-text-primary">Artifacts ({run.artifacts.length})</h2>
        {run.artifacts.length === 0 ? (
          <p className="text-sm text-text-muted">No artifacts have been registered for this run.</p>
        ) : (
          <DataTable
            caption="Artifacts registered for this run"
            rows={run.artifacts}
            rowKey={(row) => row.id}
            columns={[
              { header: "Name", render: (row) => row.logical_name },
              { header: "Type", render: (row) => <StatusPill status={row.artifact_type} /> },
              { header: "Size", render: (row) => formatBytes(row.size_bytes) },
              { header: "Reference", render: (row) => <code className="text-xs text-text-muted">{row.reference}</code> },
            ]}
          />
        )}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-text-muted">{label}</p>
      <p className="break-all text-text-primary">{value ?? "—"}</p>
    </div>
  );
}
