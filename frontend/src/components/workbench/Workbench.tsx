import type { ReactNode } from "react";
import type { PipelineCanvasState } from "../../types";
import { classNames } from "../../utils/format";

export function Page({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <>
      <header className="page-header">
        <div>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        <a className="legacy-button" href={`${window.location.pathname}?legacy=1`}>Legacy view</a>
      </header>
      {children}
    </>
  );
}


export function Toolbar({ groups }: { groups: PipelineCanvasState["toolbar_groups"] }) {
  return (
    // `overflow-x: auto` with nothing focusable inside is a region a keyboard
    // cannot scroll, which axe reports as serious and which was true the moment
    // the two-letter buttons became labels. Focusable region, the same shape
    // `DataTable`'s wrapper already uses.
    <div className="toolbar-strip" tabIndex={0} role="region" aria-label="Pipeline toolbar actions">
      {groups.map((group) => (
        <div key={group.id} className="toolbar-group">
          <span>{group.label}</span>
          {/* These were two-letter buttons with the full name in a `title` and
              no handler: unreadable and dead at once. The group and its actions
              are real information the canvas state carries, so they stay -- as
              the labels they are, rather than as controls they are not. */}
          <div>{group.actions.map((action) => <span key={action} className="toolbar-action">{action.replace(/_/g, " ")}</span>)}</div>
        </div>
      ))}
    </div>
  );
}

const FLOW_STAGES = [
  { id: "imports", label: "Import" },
  { id: "ontology", label: "Ontology" },
  { id: "pipeline", label: "Pipeline" },
  { id: "command-center", label: "Risk" },
  { id: "approval", label: "Approval" },
  { id: "report", label: "Report" }
];

export function PlatformFlow({ currentView }: { currentView: string }) {
  const activeId = currentView === "imports" || currentView === "ontology" || currentView === "pipeline" ? currentView : "command-center";
  return (
    <nav className="platform-flow" aria-label="Evaluator workflow">
      {FLOW_STAGES.map((stage, index) => (
        <a
          key={stage.id}
          className={classNames("flow-stage", stage.id === activeId && "active", index < FLOW_STAGES.findIndex((item) => item.id === activeId) && "complete")}
          href={stage.id === "approval" || stage.id === "report" ? "/workspace/command-center" : `/workspace/${stage.id}`}
        >
          <span>{index + 1}</span>
          {stage.label}
        </a>
      ))}
    </nav>
  );
}
