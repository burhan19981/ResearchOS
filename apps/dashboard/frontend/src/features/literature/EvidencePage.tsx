import { Search } from "lucide-react";
import { useState } from "react";
import { useLiterature } from "@/api/hooks";
import { DataTable } from "@/components/ui/Table";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryState } from "@/components/ui/QueryState";
import { StatusPill } from "@/components/ui/StatusPill";
import { SubNav } from "@/components/ui/SubNav";
import { formatDateTime } from "@/lib/format";
import { useEffectiveProjectId } from "@/lib/useEffectiveProjectId";
import type { LiteratureItemResponse } from "@/types/api";

export function EvidencePage() {
  const projectId = useEffectiveProjectId();
  const [search, setSearch] = useState("");
  const query = useLiterature(projectId, { q: search || undefined });

  return (
    <div>
      <PageHeader title="Evidence" description="Literature items collected for this project." />
      <SubNav
        items={[
          { label: "Literature", to: "/dashboard/evidence", end: true },
          { label: "Gaps", to: "/dashboard/evidence/gaps" },
          { label: "Novelty", to: "/dashboard/evidence/novelty" },
        ]}
      />

      <div className="mb-4 flex items-center gap-2">
        <div className="relative w-full max-w-xs">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" aria-hidden="true" />
          <label htmlFor="literature-search" className="sr-only">
            Search literature by title or authors
          </label>
          <input
            id="literature-search"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search title or authors…"
            className="w-full rounded-md border border-border bg-surface-2 py-1.5 pl-8 pr-3 text-sm text-text-primary placeholder:text-text-muted"
          />
        </div>
      </div>

      <QueryState
        {...query}
        data={query.data}
        refetch={() => void query.refetch()}
        isEmpty={(items) => items.length === 0}
        emptyTitle={search ? "No literature items match this search." : "No literature items have been collected yet."}
      >
        {(items) => <LiteratureTable items={items} />}
      </QueryState>
    </div>
  );
}

function LiteratureTable({ items }: { items: LiteratureItemResponse[] }) {
  return (
    <DataTable
      caption="Literature items for the selected project"
      rows={items}
      rowKey={(row) => row.id}
      columns={[
        {
          header: "Title",
          render: (row) => (
            <div>
              <p className="font-medium text-text-primary">{row.title}</p>
              {row.authors ? <p className="text-xs text-text-muted">{row.authors}</p> : null}
            </div>
          ),
        },
        { header: "Year", render: (row) => row.year ?? row.publication_date ?? "—" },
        { header: "Source", render: (row) => row.source ?? "—" },
        { header: "Publisher", render: (row) => row.publisher ?? "—" },
        { header: "DOI", render: (row) => row.doi ?? "—" },
        { header: "Evidence Status", render: (row) => <StatusPill status={row.evidence_status} /> },
        {
          header: "Metadata Completeness",
          render: (row) => (row.metadata_completeness !== null ? `${Math.round(row.metadata_completeness * 100)}%` : "—"),
        },
        { header: "Retrieved", render: (row) => formatDateTime(row.retrieved_at) },
      ]}
    />
  );
}
