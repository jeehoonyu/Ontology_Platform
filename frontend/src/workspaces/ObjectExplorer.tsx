import { useCallback, useEffect, useMemo, useState } from "react";
import { BookmarkPlus, ChevronRight, Filter, Network, Play, RefreshCw, Search, ShieldCheck, X } from "lucide-react";
import { EmptyState, ErrorBanner, KeyValueGrid, LoadingState, Panel, StatusBadge } from "../components/data/DataDisplay";
import { Page } from "../components/workbench/Workbench";
import {
  evaluateRisk,
  executeExplorerAction,
  getObjectProfile,
  listExplorations,
  listObjectTypes,
  queryObjects,
  saveExploration,
  type ActionResult,
  type ExplorerAction,
  type ExplorerFacet,
  type ExplorerQuery,
  type Exploration,
  type ObjectProfile,
  type ObjectRecord,
  type ObjectTypeSummary
} from "../api/objectExplorerApi";
import { formatValue } from "../utils/format";

type Risk = { score: number; band: string; explanation?: string };
type FilterValue = string | number | boolean;

function propertyValue(object: ObjectRecord, field: string): unknown {
  if (field === "id") return object.id;
  let value: unknown = object.properties;
  for (const part of field.split(".")) {
    if (!value || typeof value !== "object") return undefined;
    value = (value as Record<string, unknown>)[part];
  }
  return value;
}

function parameterNames(action: ExplorerAction): string[] {
  const value = action.parameters;
  if (Array.isArray(value)) return value.map(String);
  return Object.keys(value || {}).filter((name) => !name.endsWith("_ids"));
}

export function ObjectExplorer() {
  const requestedType = new URLSearchParams(window.location.search).get("type") || "";
  const [types, setTypes] = useState<ObjectTypeSummary[]>([]);
  const [explorations, setExplorations] = useState<Exploration[]>([]);
  const [objectTypeId, setObjectTypeId] = useState(requestedType);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Record<string, FilterValue>>({});
  const [query, setQuery] = useState<ExplorerQuery | null>(null);
  const [risk, setRisk] = useState<Record<string, Risk>>({});
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [profile, setProfile] = useState<ObjectProfile | null>(null);
  const [activeAction, setActiveAction] = useState<ExplorerAction | null>(null);
  const [actionParams, setActionParams] = useState<Record<string, string>>({});
  const [actionResult, setActionResult] = useState<ActionResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const runQuery = useCallback(async (typeId = objectTypeId, nextFilters = filters, nextSearch = search) => {
    if (!typeId) return;
    setLoading(true);
    setError("");
    try {
      const result = await queryObjects({ object_type_id: typeId, query: nextSearch, filters: nextFilters, selected_ids: selectedIds, limit: 500 });
      setQuery(result);
      setSelectedIds((ids) => ids.filter((id) => result.objects.some((object) => object.id === id)));
      try {
        const evaluated = await evaluateRisk(typeId, result.objects.map((object) => object.id));
        setRisk(Object.fromEntries(evaluated.findings.map((finding) => [finding.object_id, finding.risk])));
      } catch {
        setRisk({});
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Object query failed");
    } finally {
      setLoading(false);
    }
  }, [filters, objectTypeId, search, selectedIds]);

  useEffect(() => {
    Promise.all([listObjectTypes(), listExplorations()]).then(([nextTypes, saved]) => {
      setTypes(nextTypes);
      setExplorations(saved);
      const typeId = nextTypes.some((type) => type.id === requestedType) ? requestedType : nextTypes[0]?.id || "";
      setObjectTypeId(typeId);
      if (typeId) void runQuery(typeId, {}, "");
      else setLoading(false);
    }).catch((cause) => {
      setError(cause instanceof Error ? cause.message : "Object Explorer failed to load");
      setLoading(false);
    });
    // Initial load intentionally uses the URL type and an empty query.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectObject = async (object: ObjectRecord) => {
    setSelectedIds((ids) => ids.includes(object.id) ? ids : [...ids, object.id]);
    setError("");
    try {
      setProfile(await getObjectProfile(objectTypeId, object.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Object profile failed to load");
    }
  };

  const applyFacet = (facet: ExplorerFacet, value: FilterValue) => {
    const next = { ...filters, [facet.field]: value };
    setFilters(next);
    void runQuery(objectTypeId, next, search);
  };

  const openExploration = (saved: Exploration) => {
    setObjectTypeId(saved.object_type_id);
    setFilters(saved.filters as Record<string, FilterValue>);
    setSearch(String(saved.perspective?.query || ""));
    void runQuery(saved.object_type_id, saved.filters as Record<string, FilterValue>, String(saved.perspective?.query || ""));
  };

  const persistExploration = async () => {
    if (!query) return;
    const name = window.prompt("Exploration name", `${query.object_type?.display_name || objectTypeId} investigation`);
    if (!name) return;
    try {
      const saved = await saveExploration({
        project_id: types.find((type) => type.id === objectTypeId)?.project_id || "default",
        display_name: name,
        description: `Saved from Object Explorer with ${query.result_count} results`,
        object_type_id: objectTypeId,
        filters,
        columns: query.columns,
        charts: query.facets,
        perspective: { query: search },
        owner: "object-explorer-ui"
      });
      setExplorations((items) => [saved, ...items]);
      setNotice(`Saved exploration ${saved.display_name}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Exploration could not be saved");
    }
  };

  const runAction = async () => {
    if (!activeAction || !selectedIds.length) return;
    const params: Record<string, unknown> = { ...actionParams };
    if (!("object_id" in params)) params.object_id = selectedIds[0];
    if (!("object_ids" in params)) params.object_ids = selectedIds;
    try {
      const result = await executeExplorerAction(activeAction.id, params);
      setActionResult(result);
      setNotice(result.message);
      setActiveAction(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Action execution failed");
    }
  };

  const columns = query?.columns.slice(0, 8) || [];
  const selectedType = types.find((type) => type.id === objectTypeId);

  return (
    <Page title="Object Explorer" subtitle="Search ontology objects, filter with live facets, inspect relationships, and run governed actions.">
      <div className="explorer-command-bar">
        <label><span>Object type</span><select aria-label="Object type" value={objectTypeId} onChange={(event) => { setObjectTypeId(event.target.value); setFilters({}); setProfile(null); void runQuery(event.target.value, {}, search); }}>{types.map((type) => <option key={type.id} value={type.id}>{type.display_name}</option>)}</select></label>
        <label className="explorer-search"><Search size={16} /><input aria-label="Search objects" value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void runQuery(); }} placeholder="Search objects and properties" /></label>
        <button className="primary" onClick={() => void runQuery()}><Play size={15} />Run</button>
        <button onClick={() => void persistExploration()} disabled={!query}><BookmarkPlus size={15} />Save view</button>
        <button aria-label="Refresh exploration" title="Refresh" onClick={() => void runQuery()}><RefreshCw size={15} /></button>
      </div>
      <ErrorBanner message={error} />
      {notice ? <div className="inline-success" role="status">{notice}</div> : null}
      <div className="explorer-layout">
        <aside className="explorer-left-rail">
          <Panel title="Saved Explorations">
            <div className="explorer-saved-list">{explorations.map((saved) => <button key={saved.id} onClick={() => openExploration(saved)}><span><strong>{saved.display_name}</strong><small>{saved.object_type_id}</small></span><ChevronRight size={14} /></button>)}</div>
            {!explorations.length ? <div className="empty">Save a query to return to it later.</div> : null}
          </Panel>
          <Panel title="Filters" action={<Filter size={15} />}>
            <div className="filter-chip-list">{Object.entries(filters).map(([field, value]) => <button key={field} onClick={() => { const next = { ...filters }; delete next[field]; setFilters(next); void runQuery(objectTypeId, next, search); }} title="Remove filter"><span>{field}: {String(value)}</span><X size={12} /></button>)}</div>
            {!Object.keys(filters).length ? <div className="empty compact">Select a facet value to filter results.</div> : null}
          </Panel>
          <div className="facet-stack">{query?.facets.map((facet) => <section className="facet-card-react" key={facet.field}><header><strong>{facet.field}</strong><small>{facet.type}</small></header>{facet.buckets.slice(0, 7).map((bucket, index) => { const value = bucket.value ?? bucket.label ?? index; const max = Math.max(...facet.buckets.map((item) => item.count), 1); return <button key={`${String(value)}-${index}`} onClick={() => applyFacet(facet, value as FilterValue)}><span>{bucket.label || String(bucket.value)}</span><i style={{ width: `${Math.max(5, bucket.count / max * 100)}%` }} /><b>{bucket.count}</b></button>; })}</section>)}</div>
        </aside>

        <main className="explorer-results-panel">
          <header className="explorer-results-header"><div><h2>{query?.object_type?.display_name || selectedType?.display_name || "Objects"}</h2><span>{query ? `${query.result_count} results across ${columns.length} visible fields` : "Run an exploration"}</span></div><StatusBadge value={selectedIds.length ? `${selectedIds.length} selected` : "ready"} /></header>
          {loading ? <LoadingState label="Evaluating object set and risk..." /> : null}
          {!loading && !query?.objects.length ? <EmptyState title="No matching objects" description="Change the object type, search phrase, or active facet filters." /> : null}
          {!loading && query?.objects.length ? <div className="table-wrap explorer-table" tabIndex={0}><table><thead><tr><th className="selection-cell"><input aria-label="Select all objects" type="checkbox" checked={selectedIds.length === query.objects.length} onChange={(event) => setSelectedIds(event.target.checked ? query.objects.map((object) => object.id) : [])} /></th><th>Object</th><th>Risk</th>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{query.objects.map((object) => <tr key={object.id} className={profile?.object.id === object.id ? "selected" : ""} onClick={() => void selectObject(object)}><td className="selection-cell" onClick={(event) => event.stopPropagation()}><input aria-label={`Select ${object.id}`} type="checkbox" checked={selectedIds.includes(object.id)} onChange={(event) => setSelectedIds((ids) => event.target.checked ? [...new Set([...ids, object.id])] : ids.filter((id) => id !== object.id))} /></td><td><button className="object-link" onClick={() => void selectObject(object)}>{object.id}</button></td><td><StatusBadge value={risk[object.id] ? `${risk[object.id].band} ${risk[object.id].score}` : "not scored"} /></td>{columns.map((column) => <td key={column} title={formatValue(propertyValue(object, column))}>{formatValue(propertyValue(object, column))}</td>)}</tr>)}</tbody></table></div> : null}
        </main>

        <aside className="explorer-inspector">
          <Panel title="Object Preview" action={<Network size={15} />}>
            {!profile ? <div className="empty">Select a result to inspect its properties and links.</div> : <><header className="object-profile-heading"><div><strong>{formatValue(profile.object.properties.name || profile.object.properties.title || profile.object.id)}</strong><small>{profile.object.id}</small></div><StatusBadge value={risk[profile.object.id]?.band || "unscored"} /></header><KeyValueGrid data={profile.object.properties} /><div className="object-profile-metrics"><span>{profile.inbound_links.length} inbound</span><span>{profile.outbound_links.length} outbound</span><span>{profile.linked_objects.length} linked</span></div>{risk[profile.object.id]?.explanation ? <p className="risk-explanation"><ShieldCheck size={15} />{risk[profile.object.id].explanation}</p> : null}</>}
          </Panel>
          <Panel title="Governed Actions">
            {!query?.available_actions.length ? <div className="empty">No actions are bound to this object type.</div> : <div className="explorer-action-list">{query.available_actions.map((action) => <button key={action.id} disabled={!selectedIds.length} onClick={() => { setActiveAction(action); setActionParams({}); }}><span><strong>{action.display_name}</strong><small>{action.description || `${action.id} action`}</small></span><ChevronRight size={14} /></button>)}</div>}
            {actionResult ? <div className="action-result"><StatusBadge value={actionResult.status} /><span>{actionResult.approval_request_id ? `Approval ${actionResult.approval_request_id}` : actionResult.message}</span></div> : null}
          </Panel>
        </aside>
      </div>
      {activeAction ? <div className="modal-backdrop" role="presentation" onMouseDown={() => setActiveAction(null)}><section className="action-modal" role="dialog" aria-modal="true" aria-labelledby="bulk-action-title" onMouseDown={(event) => event.stopPropagation()}><header><div><h2 id="bulk-action-title">{activeAction.display_name}</h2><p>{selectedIds.length} selected object{selectedIds.length === 1 ? "" : "s"}</p></div><button aria-label="Close action" onClick={() => setActiveAction(null)}><X size={16} /></button></header>{parameterNames(activeAction).filter((name) => name !== "object_id").map((name) => <label key={name}><span>{name.replace(/_/g, " ")}</span><input value={actionParams[name] || ""} onChange={(event) => setActionParams((values) => ({ ...values, [name]: event.target.value }))} /></label>)}<div className="button-row"><button onClick={() => setActiveAction(null)}>Cancel</button><button className="primary" onClick={() => void runAction()}><ShieldCheck size={15} />Evaluate and run</button></div></section></div> : null}
    </Page>
  );
}
