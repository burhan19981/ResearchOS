import { CheckCircle2, Circle, Lock } from "lucide-react";
import { usePipeline } from "@/api/hooks";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryState } from "@/components/ui/QueryState";
import { humanizeToken } from "@/lib/format";
import { useEffectiveProjectId } from "@/lib/useEffectiveProjectId";
import type { PipelineResponse } from "@/types/api";

/**
 * A read-only visualization of `researchos.workflow`'s real state
 * machine — every stage/order/current-position/allowed-transition
 * value comes directly from `GET /pipeline`; nothing here computes or
 * guesses stage ordering (Dashboard V1 spec section 9).
 */
export function PipelinePage() {
  const projectId = useEffectiveProjectId();
  const query = usePipeline(projectId);

  return (
    <div>
      <PageHeader title="Research Pipeline" description="The project's real position in ResearchOS's 20-stage workflow." />
      <QueryState {...query} data={query.data} refetch={() => void query.refetch()}>
        {(pipeline) => <PipelineTimeline pipeline={pipeline} />}
      </QueryState>
    </div>
  );
}

function PipelineTimeline({ pipeline }: { pipeline: PipelineResponse }) {
  const allowedTargets = new Set(pipeline.allowed_transitions.map((t) => t.target_stage));

  return (
    <div>
      <ol className="flex flex-col gap-0.5">
        {pipeline.stages.map((stage) => {
          const isAllowedNext = allowedTargets.has(stage.stage);
          return (
            <li key={stage.stage} className="flex items-center gap-3 py-1.5">
              <span aria-hidden="true">
                {stage.is_completed ? (
                  <CheckCircle2 size={18} className="text-status-success" />
                ) : stage.is_current ? (
                  <Circle size={18} className="fill-accent text-accent" />
                ) : (
                  <Circle size={18} className="text-text-muted" />
                )}
              </span>
              <span
                className={`text-sm ${
                  stage.is_current ? "font-semibold text-text-primary" : stage.is_completed ? "text-text-secondary" : "text-text-muted"
                }`}
              >
                {humanizeToken(stage.stage)}
              </span>
              {stage.is_current ? (
                <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[11px] font-medium text-accent">Current</span>
              ) : null}
              {isAllowedNext ? (
                <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-text-muted">Allowed next</span>
              ) : null}
            </li>
          );
        })}
      </ol>

      {pipeline.allowed_transitions.length > 0 ? (
        <div className="mt-6">
          <h2 className="mb-2 text-sm font-semibold text-text-primary">Allowed Transitions</h2>
          <ul className="flex flex-col gap-1.5">
            {pipeline.allowed_transitions.map((t) => (
              <li key={t.target_stage} className="flex items-center gap-2 text-sm text-text-secondary">
                {t.policy === "human_only" || t.policy === "approval_required" ? (
                  <Lock size={13} className="text-text-muted" aria-hidden="true" />
                ) : null}
                {humanizeToken(t.target_stage)}
                <span className="text-xs text-text-muted">({humanizeToken(t.policy)}, {t.direction})</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="mt-6 text-sm text-text-muted">No transitions are currently allowed for this project.</p>
      )}
    </div>
  );
}
