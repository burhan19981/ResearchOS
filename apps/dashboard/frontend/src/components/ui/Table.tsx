import type { ReactNode } from "react";

interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  caption: string;
}

/** A semantic, accessible `<table>` — a real caption (visually hidden
 * but announced by screen readers), real `<th scope="col">` headers,
 * never a div-grid pretending to be a table (Dashboard V1 spec section
 * 27). */
export function DataTable<T>({ columns, rows, rowKey, caption }: DataTableProps<T>) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-max text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-border-subtle text-xs uppercase tracking-wide text-text-muted">
            {columns.map((col) => (
              <th key={col.header} scope="col" className={`px-3 py-2 font-medium ${col.className ?? ""}`}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="border-b border-border-subtle last:border-0 hover:bg-surface-2/60">
              {columns.map((col) => (
                <td key={col.header} className={`px-3 py-2 align-top text-text-primary ${col.className ?? ""}`}>
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
