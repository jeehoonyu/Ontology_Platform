import { useMemo, type ReactNode } from "react";
import { asString, classNames, formatValue } from "../../utils/format";
import type { JsonObject, TableRow } from "../../types";

export function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel">
      <header className="panel-header">
        <h2>{title}</h2>
        {action}
      </header>
      {children}
    </section>
  );
}

export function StatusBadge({ value }: { value?: string | number | null }) {
  const text = String(value ?? "unknown");
  const tone = text.toLowerCase();
  return (
    <span
      className={classNames(
        "badge",
        tone.includes("fail") || tone.includes("critical") || tone.includes("error") ? "bad" : false,
        tone.includes("warn") || tone.includes("pending") || tone.includes("active") ? "warn" : false
      )}
    >
      {text}
    </span>
  );
}

export function DataTable({ rows, empty = "No records" }: { rows?: TableRow[]; empty?: string }) {
  const safeRows = rows || [];
  const columns = useMemo(() => {
    const seen = new Set<string>();
    for (const row of safeRows.slice(0, 10)) Object.keys(row || {}).slice(0, 8).forEach((key) => seen.add(key));
    return Array.from(seen);
  }, [safeRows]);
  if (!safeRows.length) return <div className="empty">{empty}</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {safeRows.slice(0, 40).map((row, index) => (
            <tr key={index}>{columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function KeyValueGrid({ data }: { data: JsonObject }) {
  const entries = Object.entries(data || {});
  if (!entries.length) return <div className="empty">No details available.</div>;
  return (
    <dl className="kv-grid">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key.replace(/_/g, " ")}</dt>
          <dd>{formatValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Metric({ label, value }: { label: string; value: unknown }) {
  return (
    <article className="metric-card">
      <strong>{formatValue(value)}</strong>
      <span>{label}</span>
    </article>
  );
}

export function RelationshipStrip({ rows, fallback }: { rows: TableRow[]; fallback: string }) {
  if (!rows.length) {
    return (
      <div className="relationship-strip">
        <span>{fallback}</span>
        <button>Create new link type</button>
      </div>
    );
  }
  return (
    <div className="relationship-strip">
      {rows.map((row) => (
        <article key={asString(row.id)}>
          <span>{formatValue(row.source_object_type_id)}</span>
          <strong>{formatValue(row.display_name || row.id)}</strong>
          <span>{formatValue(row.target_object_type_id)}</span>
        </article>
      ))}
    </div>
  );
}

export function DebugJson({ title, value }: { title: string; value: unknown }) {
  if (!value) return null;
  return (
    <details className="debug-json">
      <summary>{title}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
