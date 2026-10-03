export type StatusTone = "success" | "warning" | "danger" | "info" | "neutral";

const SUCCESS_TOKENS = ["approved", "succeeded", "completed", "valid", "ready", "human_approved", "supported"];
const DANGER_TOKENS = ["rejected", "failed", "invalid", "contradicted", "cancelled", "timeout", "not_comparable"];
const WARNING_TOKENS = [
  "pending", "candidate", "draft", "changes_requested", "needs_more_evidence", "not_assessed",
  "unreviewed", "insufficient_evidence",
];
const INFO_TOKENS = ["running", "queued", "validating", "active", "partially_supported"];

/**
 * A generic, keyword-based status -> visual-tone classifier spanning
 * every status vocabulary in the app (RunStatus, ApprovalDecision,
 * PlanningApprovalStatus, ClaimStrength, ScientificReviewStatus,
 * NoveltyCandidateStatus, ...) rather than one hard-coded switch per
 * enum. Tone is always paired with the literal status text and an
 * icon in `StatusPill` — never the only signal (Dashboard V1 spec
 * section 27: never communicate state using color alone).
 */
export function statusTone(status: string | null | undefined): StatusTone {
  if (!status) return "neutral";
  const normalized = status.toLowerCase();
  if (DANGER_TOKENS.some((t) => normalized.includes(t))) return "danger";
  if (SUCCESS_TOKENS.some((t) => normalized.includes(t))) return "success";
  if (WARNING_TOKENS.some((t) => normalized.includes(t))) return "warning";
  if (INFO_TOKENS.some((t) => normalized.includes(t))) return "info";
  return "neutral";
}
