import { useScientificClaims } from "@/api/hooks";
import { Card, CardBody } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryState } from "@/components/ui/QueryState";
import { StatusPill } from "@/components/ui/StatusPill";
import { SubNav } from "@/components/ui/SubNav";
import { humanizeToken } from "@/lib/format";
import { useEffectiveProjectId } from "@/lib/useEffectiveProjectId";
import type { ScientificClaimResponse } from "@/types/api";

/**
 * Claim strength/approval status and review status are read verbatim
 * from the existing domain vocabularies — never collapsed into a
 * blunt true/false (Dashboard V1 spec section 17).
 */
export function ReviewsPage() {
  const projectId = useEffectiveProjectId();
  const query = useScientificClaims(projectId);

  return (
    <div>
      <PageHeader title="Scientific Claims & Reviews" />
      <SubNav items={[{ label: "Analysis Records", to: "/dashboard/analysis", end: true }, { label: "Reviews & Claims", to: "/dashboard/analysis/reviews" }]} />
      <QueryState
        {...query}
        data={query.data}
        refetch={() => void query.refetch()}
        isEmpty={(rows) => rows.length === 0}
        emptyTitle="No scientific claims exist yet."
      >
        {(claims) => (
          <div className="flex flex-col gap-3">
            {claims.map((claim) => (
              <ClaimCard key={claim.id} claim={claim} />
            ))}
          </div>
        )}
      </QueryState>
    </div>
  );
}

function ClaimCard({ claim }: { claim: ScientificClaimResponse }) {
  return (
    <Card>
      <CardBody>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <StatusPill status={claim.approval_status} />
          <StatusPill status={claim.strength} />
          {claim.confidence !== null ? (
            <span className="text-xs text-text-muted">Confidence: {Math.round(claim.confidence * 100)}%</span>
          ) : null}
        </div>
        <p className="text-sm text-text-primary">{claim.claim_text}</p>
        <p className="mt-1 text-[11px] text-text-muted">
          Supported by analysis record(s): {claim.supporting_analysis_record_ids.join(", ") || "none"}
        </p>

        {claim.reviews.length > 0 ? (
          <div className="mt-3 border-t border-border-subtle pt-3">
            <p className="mb-1.5 text-xs font-semibold text-text-secondary">Scientific Reviews ({claim.reviews.length})</p>
            <ul className="flex flex-col gap-2">
              {claim.reviews.map((review) => (
                <li key={review.id} className="text-sm">
                  <div className="flex items-center gap-2">
                    <StatusPill status={review.status} />
                    <span className="text-xs text-text-muted">v{review.version}</span>
                  </div>
                  {review.recommendation ? <p className="mt-1 text-xs text-text-secondary">{review.recommendation}</p> : null}
                  {review.dimensions ? (
                    <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] sm:grid-cols-3">
                      {Object.entries(review.dimensions).map(([key, value]) => (
                        <div key={key}>
                          <dt className="text-text-muted">{humanizeToken(key)}</dt>
                          <dd className="text-text-secondary">{value}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="mt-2 text-xs text-text-muted">No scientific review has been started for this claim yet.</p>
        )}
      </CardBody>
    </Card>
  );
}
