import type { ReactNode } from "react";
import type { PipelineCanvasState } from "../../types";

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

export function WorkspaceHeader({ title, tabs, actions }: { title: string; tabs: string[]; actions: ReactNode }) {
  return (
    <div className="workspace-header">
      <div>
        <strong>{title}</strong>
        <span>Batch</span>
      </div>
      <nav>{tabs.map((tab) => <button key={tab} className={tab === "Graph" ? "active" : ""}>{tab}</button>)}</nav>
      <div className="button-row">{actions}</div>
    </div>
  );
}

export function Toolbar({ groups }: { groups: PipelineCanvasState["toolbar_groups"] }) {
  return (
    <div className="toolbar-strip">
      {groups.map((group) => (
        <div key={group.id} className="toolbar-group">
          <span>{group.label}</span>
          <div>{group.actions.slice(0, 8).map((action) => <button key={action} title={action}>{action.slice(0, 2).toUpperCase()}</button>)}</div>
        </div>
      ))}
    </div>
  );
}
