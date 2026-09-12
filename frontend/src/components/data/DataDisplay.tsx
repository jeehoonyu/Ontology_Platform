import { useMemo, type ReactNode } from "react";
import { asString, classNames, formatValue } from "../../utils/format";
import { renderPropertyValue, type PropertySpec } from "../../utils/semanticRender";
import type { EvidenceLink, JsonObject, TableRow, UiSection, UiWarning } from "../../types";

export function Panel({ title, action, children, className, ariaLabel }: { title: string; action?: ReactNode; children: ReactNode; className?: string; ariaLabel?: string }) {
  return (
    <section className={classNames("panel", className)} aria-label={ariaLabel}>
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

/**
 * The one place "there is nothing here" is rendered.
 *
 * Two treatments existed and both are kept, because they are not the same
 * thing visually and `.empty` is not a lesser version of `.empty-state-card` --
 * it is the terser one, and it is the app's most common, used at 42 sites
 * against the card's handful. Collapsing them would have been a design change
 * dressed as a cleanup.
 *
 * What was actually wrong is that only one of the two had a component, so only
 * one was countable or changeable in a single place. `inline` renders the other
 * one, byte for byte:
 *
 *   <div className="empty">…</div>   ->   <EmptyState inline>…</EmptyState>
 *
 * `audit_ui_states.py` counts the raw form that remains and ratchets it down.
 */
export function EmptyState({ title, description, action, inline, compact, children }: {
  title?: string;
  description?: string;
  action?: ReactNode;
  inline?: boolean;
  compact?: boolean;
  children?: ReactNode;
}) {
  if (inline) {
    return <div className={compact ? "empty compact" : "empty"}>{children ?? description}</div>;
  }
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
export const TABLE_ROW_LIMIT = 40;

export function DataTable({ rows, specs, empty = "No records" }: { rows?: TableRow[]; specs?: Record<string, PropertySpec>; empty?: string }) {
  const safeRows = rows || [];
  const columns = useMemo(() => {
    // Every row, and every key. This read the first ten rows and took eight
    // keys from each, so a field that first appeared in row eleven had no
    // column -- and its value was then missing from every row, including the
    // ten that were sampled. That is the truncation that never looked like one:
    // forty complete-looking rows with three fields silently absent.
    const seen = new Set<string>();
    for (const row of safeRows) Object.keys(row || {}).forEach((key) => seen.add(key));
    return Array.from(seen);
  }, [safeRows]);
  if (!safeRows.length) return <div className="empty">{empty}</div>;
  const shown = safeRows.slice(0, TABLE_ROW_LIMIT);
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table">
      <table>
        {/* A limit a person can see is a limit; a limit a person cannot see is
            a wrong answer. This comes from the component rather than from each
            of the seventy-five call sites, because a convention seventy-five
            places have to remember is one that will be wrong in some of them
            and nobody will know which. */}
        {shown.length < safeRows.length ? (
          <caption className="table-truncated">
            Showing {shown.length.toLocaleString()} of {safeRows.length.toLocaleString()} rows
          </caption>
        ) : null}
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {shown.map((row, index) => (
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
