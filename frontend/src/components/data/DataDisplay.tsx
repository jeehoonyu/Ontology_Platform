import { useMemo, type ReactNode } from "react";
import { asString, classNames, formatValue } from "../../utils/format";
import { renderPropertyValue, type PropertySpec } from "../../utils/semanticRender";
import type { EvidenceLink, JsonObject, TableRow, UiSection, UiWarning } from "../../types";

export function Panel({ title, action, children, className }: { title: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={classNames("panel", className)}>
      <header className="panel-header">
        <h2>{title}</h2>
        {action}
      </header>
      {children}
    </section>
  );
}

export function LoadingState({ label = "Loading workspace data..." }: { label?: string }) {
  return <div className="state-block loading-state">{label}</div>;
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="state-block empty-state-card">
      <strong>{title}</strong>
      {description ? <span>{description}</span> : null}
      {action ? <div className="button-row">{action}</div> : null}
    </div>
  );
}

export function ErrorBanner({ message }: { message?: string }) {
  if (!message) return null;
  return <div className="state-block error-state">{message}</div>;
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

export function WarningList({ warnings }: { warnings?: UiWarning[] }) {
  if (!warnings?.length) return null;
  return (
    <div className="warning-list">
      {warnings.map((warning) => (
        <article key={warning.id}>
          <StatusBadge value={warning.severity || "info"} />
          <span>{warning.message}</span>
        </article>
      ))}
    </div>
  );
}

/**
 * `specs` is optional, so every existing caller keeps its current rendering.
 * Supplied, cells are drawn by the base type the ontology declares rather than
 * stringified -- the same dispatch `KeyValueGrid` uses, so a table and a detail
 * pane of the same object agree on how its geometry or its timestamp reads.
 */
export function DataTable({ rows, specs, empty = "No records" }: { rows?: TableRow[]; specs?: Record<string, PropertySpec>; empty?: string }) {
  const safeRows = rows || [];
  const columns = useMemo(() => {
    const seen = new Set<string>();
    for (const row of safeRows.slice(0, 10)) Object.keys(row || {}).slice(0, 8).forEach((key) => seen.add(key));
    return Array.from(seen);
  }, [safeRows]);
  if (!safeRows.length) return <div className="empty">{empty}</div>;
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table">
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {safeRows.slice(0, 40).map((row, index) => (
            <tr key={index}>{columns.map((column) => {
              const text = formatValue(row[column]);
              return <td key={column} title={text}>{specs ? renderPropertyValue(row[column], specs[column]) : text}</td>;
            })}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * `specs` is optional so every existing caller keeps its current rendering.
 * When the ontology's declared types are supplied, values are drawn by type --
 * a geopoint as a location, a timestamp in the viewer's zone, a decimal with
 * its unit -- instead of being stringified.
 */
export function KeyValueGrid({ data, specs }: { data: JsonObject; specs?: Record<string, PropertySpec> }) {
  const entries = Object.entries(data || {});
  if (!entries.length) return <div className="empty">No details available.</div>;
  return (
    <dl className="kv-grid">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key.replace(/_/g, " ")}</dt>
          <dd>{specs ? renderPropertyValue(value, specs[key]) : formatValue(value)}</dd>
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

export function SectionCards({ sections, onNavigate }: { sections?: UiSection[]; onNavigate?: (href: string) => void }) {
  if (!sections?.length) return <EmptyState title="No sections available" description="Run the sample workflow or refresh the workspace." />;
  return (
    <div className="section-card-grid">
      {sections.map((section) => (
        <article key={section.id} className="section-card">
          <header>
            <div>
              <strong>{section.title}</strong>
              {section.description ? <span>{section.description}</span> : null}
            </div>
            <StatusBadge value={section.status || "available"} />
          </header>
          {section.metrics ? <KeyValueGrid data={section.metrics} /> : null}
          {section.href ? (
            <button onClick={() => onNavigate?.(section.href || "")}>Open evidence</button>
          ) : null}
        </article>
      ))}
    </div>
  );
}

export function EvidenceList({ links }: { links?: EvidenceLink[] }) {
  const safeLinks = (links || []).filter((link) => link.id);
  if (!safeLinks.length) return <div className="empty">No evidence links yet.</div>;
  return (
    <ol className="proof-trail evidence-list">
      {safeLinks.map((link) => (
        <li key={`${link.kind}-${link.id}`}>
          <span>{link.kind.replace(/_/g, " ")}</span>
          <a href={link.href}>{link.id}</a>
        </li>
      ))}
    </ol>
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

export function DeveloperEvidence({ title = "Developer evidence", children }: { title?: string; children: ReactNode }) {
  return (
    <details className="developer-evidence">
      <summary>{title}</summary>
      <div>{children}</div>
    </details>
  );
}

export function DebugJson({ title, value }: { title: string; value: unknown }) {
  if (!value) return null;
  return (
    <DeveloperEvidence title={title}>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </DeveloperEvidence>
  );
}
