import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/apiClient";
import { queryKeys } from "@/lib/queryClient";
import type {
  AnalysisRecordResponse,
  ApprovalActionRequest,
  ApprovalActionResponse,
  ApprovalResponse,
  AuditEventResponse,
  ExperimentResponse,
  HealthResponse,
  LiteratureItemResponse,
  NoveltyAssessmentResponse,
  OverviewResponse,
  PipelineResponse,
  PlanningResponse,
  ProjectResponse,
  ResearchGapResponse,
  RunResponse,
  ScientificClaimResponse,
} from "@/types/api";

export function useHealth() {
  return useQuery({ queryKey: queryKeys.health(), queryFn: () => apiGet<HealthResponse>("/health") });
}

export function useProjects() {
  return useQuery({ queryKey: queryKeys.projects(), queryFn: () => apiGet<ProjectResponse[]>("/projects") });
}

export function useProject(projectId: number | null) {
  return useQuery({
    queryKey: projectId === null ? ["projects", "none"] : queryKeys.project(projectId),
    queryFn: () => apiGet<ProjectResponse>(`/projects/${projectId}`),
    enabled: projectId !== null,
  });
}

export function useOverview(projectId: number | null) {
  return useQuery({
    queryKey: projectId === null ? ["overview", "none"] : queryKeys.overview(projectId),
    queryFn: () => apiGet<OverviewResponse>(`/projects/${projectId}/overview`),
    enabled: projectId !== null,
  });
}

export function usePipeline(projectId: number | null) {
  return useQuery({
    queryKey: projectId === null ? ["pipeline", "none"] : queryKeys.pipeline(projectId),
    queryFn: () => apiGet<PipelineResponse>(`/projects/${projectId}/pipeline`),
    enabled: projectId !== null,
  });
}

export function useLiterature(projectId: number | null, params?: { q?: string }) {
  const search = params?.q ? `?q=${encodeURIComponent(params.q)}` : "";
  return useQuery({
    queryKey: projectId === null ? ["literature", "none"] : [...queryKeys.literature(projectId), params?.q ?? ""],
    queryFn: () => apiGet<LiteratureItemResponse[]>(`/projects/${projectId}/literature${search}`),
    enabled: projectId !== null,
  });
}

export function useGaps(projectId: number | null) {
  return useQuery({
    queryKey: projectId === null ? ["gaps", "none"] : queryKeys.gaps(projectId),
    queryFn: () => apiGet<ResearchGapResponse[]>(`/projects/${projectId}/gaps`),
    enabled: projectId !== null,
  });
}

export function useNovelty(projectId: number | null) {
  return useQuery({
    queryKey: projectId === null ? ["novelty", "none"] : queryKeys.novelty(projectId),
    queryFn: () => apiGet<NoveltyAssessmentResponse[]>(`/projects/${projectId}/novelty`),
    enabled: projectId !== null,
  });
}

export function usePlanning(projectId: number | null) {
  return useQuery({
    queryKey: projectId === null ? ["planning", "none"] : queryKeys.planning(projectId),
    queryFn: () => apiGet<PlanningResponse>(`/projects/${projectId}/planning`),
    enabled: projectId !== null,
  });
}

export function useExperiments(projectId: number | null) {
  return useQuery({
    queryKey: projectId === null ? ["experiments", "none"] : queryKeys.experiments(projectId),
    queryFn: () => apiGet<ExperimentResponse[]>(`/projects/${projectId}/experiments`),
    enabled: projectId !== null,
  });
}

export function useExperiment(projectId: number | null, experimentId: number | null) {
  return useQuery({
    queryKey:
      projectId === null || experimentId === null
        ? ["experiment", "none"]
        : queryKeys.experiment(projectId, experimentId),
    queryFn: () => apiGet<ExperimentResponse>(`/projects/${projectId}/experiments/${experimentId}`),
    enabled: projectId !== null && experimentId !== null,
  });
}

export function useRuns(projectId: number | null, experimentId?: number | null) {
  const search = experimentId ? `?experiment_id=${experimentId}` : "";
  return useQuery({
    queryKey: projectId === null ? ["runs", "none"] : queryKeys.runs(projectId, experimentId),
    queryFn: () => apiGet<RunResponse[]>(`/projects/${projectId}/runs${search}`),
    enabled: projectId !== null,
  });
}

export function useRun(projectId: number | null, runId: number | null) {
  return useQuery({
    queryKey: projectId === null || runId === null ? ["run", "none"] : queryKeys.run(projectId, runId),
    queryFn: () => apiGet<RunResponse>(`/projects/${projectId}/runs/${runId}`),
    enabled: projectId !== null && runId !== null,
  });
}

export function useAnalysisRecords(projectId: number | null) {
  return useQuery({
    queryKey: projectId === null ? ["analysis", "none"] : queryKeys.analysis(projectId),
    queryFn: () => apiGet<AnalysisRecordResponse[]>(`/projects/${projectId}/analysis`),
    enabled: projectId !== null,
  });
}

export function useScientificClaims(projectId: number | null) {
  return useQuery({
    queryKey: projectId === null ? ["reviews", "none"] : queryKeys.reviews(projectId),
    queryFn: () => apiGet<ScientificClaimResponse[]>(`/projects/${projectId}/reviews`),
    enabled: projectId !== null,
  });
}

export function useApprovals(projectId: number | null) {
  return useQuery({
    queryKey: projectId === null ? ["approvals", "none"] : queryKeys.approvals(projectId),
    queryFn: () => apiGet<ApprovalResponse[]>(`/projects/${projectId}/approvals`),
    enabled: projectId !== null,
  });
}

export function useAuditEvents(projectId: number | null) {
  return useQuery({
    queryKey: projectId === null ? ["audit", "none"] : queryKeys.audit(projectId),
    queryFn: () => apiGet<AuditEventResponse[]>(`/projects/${projectId}/audit`),
    enabled: projectId !== null,
  });
}

/**
 * The Approval Center's one mutation. On success it invalidates every
 * query for the project that could plausibly be affected by an
 * approval decision — approvals themselves, the entity's own list
 * (planning/analysis/reviews/runs), the overview counts, the pipeline,
 * and the audit log — rather than trying to guess exactly which one
 * changed (Dashboard V1 spec section 25).
 */
export function useActOnApproval(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ approvalId, body }: { approvalId: number; body: ApprovalActionRequest }) =>
      apiPost<ApprovalActionResponse>(`/projects/${projectId}/approvals/${approvalId}/actions`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects", projectId] });
    },
  });
}
