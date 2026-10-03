/**
 * TypeScript mirrors of the FastAPI backend's Pydantic response
 * schemas (apps/dashboard/api/researchos_api/schemas/). Kept in sync
 * by hand — these are the stable API contracts the backend guarantees,
 * not a generated client, so a field added on one side without the
 * other is a compile error here, not a silent runtime mismatch.
 */

export interface ProjectResponse {
  id: number;
  title: string;
  description: string | null;
  field: string | null;
  status: string;
  current_stage: string | null;
  created_at: string;
  updated_at: string;
}

export interface OverviewCounts {
  literature_items: number;
  research_gaps: number;
  novelty_assessments: number;
  research_questions: number;
  contribution_candidates: number;
  experiments: number;
  runs: number;
  metrics: number;
  analysis_records: number;
  scientific_claims: number;
  scientific_reviews: number;
  pending_approvals: number;
}

export interface OverviewResponse {
  project: ProjectResponse;
  current_stage: string;
  counts: OverviewCounts;
}

export interface PipelineStage {
  stage: string;
  order: number;
  is_current: boolean;
  is_completed: boolean;
}

export interface AllowedTransition {
  target_stage: string;
  policy: string;
  direction: string;
}

export interface PipelineResponse {
  project_id: number;
  project_status: string;
  current_stage: string;
  stages: PipelineStage[];
  allowed_transitions: AllowedTransition[];
}

export interface LiteratureItemResponse {
  id: number;
  project_id: number;
  title: string;
  authors: string | null;
  year: number | null;
  venue: string | null;
  doi: string | null;
  url: string | null;
  source: string | null;
  publisher: string | null;
  publication_date: string | null;
  document_type: string | null;
  citation_count: number | null;
  evidence_status: string;
  record_status: string;
  metadata_completeness: number | null;
  retrieved_at: string | null;
  created_at: string;
}

export interface ResearchGapResponse {
  id: number;
  project_id: number;
  statement: string;
  status: string;
  gap_type: string | null;
  affected_research_area: string | null;
  evidence_summary: string | null;
  confidence: number | null;
  research_question_id: number | null;
  evidence_count: number;
  created_at: string;
  updated_at: string;
}

export interface NoveltyAssessmentResponse {
  id: number;
  project_id: number;
  claim: string;
  status: string;
  candidate_status: string;
  confidence: number | null;
  novelty_risk: string | null;
  unresolved_questions: string | null;
  research_question_id: number | null;
  contribution_candidate_id: number | null;
}

export interface ResearchQuestionResponse {
  id: number;
  project_id: number;
  question: string;
  type: string | null;
  status: string;
  planning_status: string;
}

export interface ContributionCandidateResponse {
  id: number;
  project_id: number;
  title: string;
  description: string;
  contribution_type: string | null;
  planning_status: string;
  version: number;
  cited_research_question_ids: number[];
}

export interface MethodologyPlanResponse {
  id: number;
  project_id: number;
  description: string;
  status: string;
  planning_status: string;
  methodology_type: string | null;
  version: number;
  contribution_candidate_id: number | null;
}

export interface DatasetRequirementsResponse {
  id: number;
  project_id: number;
  required_characteristics: string | null;
  planning_status: string;
  methodology_plan_id: number | null;
}

export interface ExperimentalDesignResponse {
  id: number;
  project_id: number;
  proposed_method: string | null;
  comparison_strategy: string | null;
  planning_status: string;
  version: number;
  methodology_plan_id: number | null;
  dataset_requirements_id: number | null;
}

export interface ExperimentSpecificationResponse {
  id: number;
  project_id: number;
  experiment_id: number | null;
  experimental_design_id: number | null;
  methodology_plan_id: number | null;
  dataset_version_id: number | null;
  description: string | null;
  planning_status: string;
  version: number;
  configuration_hash: string | null;
}

export interface PlanningResponse {
  project_id: number;
  research_questions: ResearchQuestionResponse[];
  contribution_candidates: ContributionCandidateResponse[];
  methodology_plans: MethodologyPlanResponse[];
  dataset_requirements: DatasetRequirementsResponse[];
  experimental_designs: ExperimentalDesignResponse[];
  experiment_specifications: ExperimentSpecificationResponse[];
}

export interface ExperimentResponse {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  status: string;
  code_version: string | null;
  dataset_version: string | null;
  random_seed: number | null;
  hardware: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  run_count: number;
  specification_count: number;
}

export interface EnvironmentSnapshotResponse {
  id: number;
  os_name: string | null;
  os_version: string | null;
  architecture: string | null;
  python_version: string | null;
  pytorch_version: string | null;
  cuda_version: string | null;
  gpu_name: string | null;
  cpu_model: string | null;
  cpu_count: number | null;
  total_memory_bytes: number | null;
  researchos_version: string | null;
}

export interface ArtifactResponse {
  id: number;
  run_id: number;
  logical_name: string;
  artifact_type: string;
  reference: string;
  size_bytes: number | null;
  content_hash: string | null;
  mime_type: string | null;
  source: string | null;
  description: string | null;
  created_at: string;
}

export interface MetricResponse {
  id: number;
  run_id: number;
  name: string;
  value: number;
  value_type: string;
  unit: string | null;
  split: string | null;
  aggregation: string | null;
  source: string | null;
  created_at: string;
}

export interface RunResponse {
  id: number;
  project_id: number;
  experiment_id: number;
  experiment_specification_id: number | null;
  dataset_version_id: number | null;
  status: string;
  execution_backend: string;
  configuration_hash: string | null;
  dataset_fingerprint: string | null;
  code_repository: string | null;
  code_commit: string | null;
  code_branch: string | null;
  working_tree_clean: boolean | null;
  seed: number | null;
  timeout_seconds: number;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  exit_code: number | null;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
  environment: EnvironmentSnapshotResponse | null;
  artifacts: ArtifactResponse[];
  metrics: MetricResponse[];
}

export interface AnalysisInputResponse {
  id: number;
  input_type: string;
  input_id: number;
}

export interface AnalysisRecordResponse {
  id: number;
  project_id: number;
  method: string;
  parameters: Record<string, unknown> | null;
  result: Record<string, unknown>;
  status: string;
  version: number;
  supersedes_id: number | null;
  software_versions: Record<string, unknown> | null;
  created_at: string;
  inputs: AnalysisInputResponse[];
}

export interface ScientificReviewResponse {
  id: number;
  project_id: number;
  claim_id: number;
  status: string;
  dimensions: Record<string, string> | null;
  recommendation: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ScientificClaimResponse {
  id: number;
  project_id: number;
  claim_text: string;
  claim_type: string | null;
  strength: string;
  approval_status: string;
  confidence: number | null;
  version: number;
  created_at: string;
  updated_at: string;
  supporting_analysis_record_ids: number[];
  reviews: ScientificReviewResponse[];
}

export interface ApprovalResponse {
  id: number;
  project_id: number;
  stage: string;
  entity_type: string;
  entity_id: number | null;
  decision: string;
  comment: string | null;
  requested_at: string;
  decided_at: string | null;
}

export type ApprovalAction = "approve" | "reject" | "request_changes";

export interface ApprovalActionRequest {
  action: ApprovalAction;
  comment?: string | null;
}

export interface ApprovalActionResponse {
  approval: ApprovalResponse;
  entity_status: string;
}

export interface AuditEventResponse {
  id: number;
  project_id: number;
  event_type: string;
  actor: string;
  description: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface ComponentHealth {
  name: string;
  healthy: boolean;
  detail: string | null;
}

export interface HealthResponse {
  healthy: boolean;
  version: string;
  components: ComponentHealth[];
}

export interface ApiErrorBody {
  error: string;
  detail: string;
}
