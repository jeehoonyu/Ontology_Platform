import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Dialog } from "../components/layout/Dialog";
import { BookmarkPlus, ChevronRight, Filter, Network, Play, RefreshCw, Search, ShieldCheck, X } from "lucide-react";
import { EmptyState, ErrorBanner, KeyValueGrid, LoadingState, Panel, StatusBadge, UnknownResource } from "../components/data/DataDisplay";
import { isNotFound } from "../api";
import { navigate, useRouteParams } from "../utils/navigation";
import { ACTION_RESULT, intentOf, RISK_BAND } from "../components/data/intents";
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
  type FacetBucket,
  type ExplorerQuery,
  type Exploration,
  type ObjectProfile,
  type ObjectRecord,
  type ObjectTypeSummary
} from "../api/objectExplorerApi";
import { formatValue } from "../utils/format";
import { propertySpecs, renderPropertyValue } from "../utils/semanticRender";

type Risk = { score: number; band: string; explanation?: string };
// A histogram bucket filters by its range: the last bin, and a single bin, include the upper
// edge, as the server counted them.
type RangeFilter = { gte: number; lt?: number; lte?: number };
type FilterValue = string | number | boolean | RangeFilter;

function filterLabel(value: FilterValue): string {
  return typeof value === "object" ? `${value.gte} – ${value.lte ?? value.lt}` : String(value);
}

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

// A value list's short view. The card drew the first seven buckets of any facet: a
// histogram's eighth bin, which holds the maximum, never showed, and a value list
// never said it had more. A histogram now draws every bin; a value list shows the seven
// most common, says how many values there are, and shows the rest on request.
const FACET_SHORT = 7;

// What a bucket filters by. A histogram bucket sent its label, "0 - 13.75", which no number
// equals, so every click read "No matching objects".
function facetFilter(facet: ExplorerFacet, bucket: FacetBucket, index: number): FilterValue {
  if (facet.type === "histogram" && bucket.range) {
    const [low, high] = bucket.range;
    return index === facet.buckets.length - 1 || low === high ? { gte: low, lte: high } : { gte: low, lt: high };
  }
  return bucket.value ?? bucket.label ?? "";
}

function FacetCard({ facet, onApply }: { facet: ExplorerFacet; onApply: (value: FilterValue) => void }) {
  const [expanded, setExpanded] = useState(false);
  const listogram = facet.type === "listogram";
  const total = facet.distinct_count ?? facet.buckets.length;
  const shown = listogram && !expanded ? facet.buckets.slice(0, FACET_SHORT) : facet.buckets;
  const max = Math.max(...facet.buckets.map((item) => item.count), 1);
  const toggleLabel = expanded
    ? `Show only the ${FACET_SHORT} most common`
    : facet.buckets.length === total ? `Show all ${total.toLocaleString()} values` : `Show the ${facet.buckets.length.toLocaleString()} most common`;
  return <section className="facet-card-react">
    <header><strong>{facet.field}</strong><small>{facet.type}</small></header>
    {listogram && shown.length < total ? <p className="table-truncated" role="note">Showing the {shown.length.toLocaleString()} most common of {total.toLocaleString()} values</p> : null}
    {shown.map((bucket, index) => {
      return <button key={`${bucket.label ?? String(bucket.value)}-${index}`} onClick={() => onApply(facetFilter(facet, bucket, index))}><span>{bucket.label || String(bucket.value)}</span><i style={{ width: `${Math.max(5, bucket.count / max * 100)}%` }} /><b>{bucket.count}</b></button>;
    })}
    {listogram && facet.buckets.length > FACET_SHORT ? <footer className="facet-card-footer"><button type="button" aria-expanded={expanded} onClick={() => setExpanded((open) => !open)}>{toggleLabel}</button></footer> : null}
  </section>;
}

export function ObjectExplorer() {
  // The URL drives the object type and the object inspected (GOAL_FOUNDATIONS A6), through the
  // two effects below. objectTypeId is the type the query shown is for.
  const route = useRouteParams("object-explorer");
  const [types, setTypes] = useState<ObjectTypeSummary[]>([]);
  const [typesLoaded, setTypesLoaded] = useState(false);
  const [explorations, setExplorations] = useState<Exploration[]>([]);
  const [objectTypeId, setObjectTypeId] = useState("");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Record<string, FilterValue>>({});
  const [loadedQuery, setQuery] = useState<ExplorerQuery | null>(null);
  // Queries answer in the order they were asked only by luck: Back and Forward now ask ones the
  // user is not waiting on. Only the latest is taken.
  const querySeq = useRef(0);
  const [risk, setRisk] = useState<Record<string, Risk>>({});
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  // The profile answers one type's object, and carries both, so nothing of one object shows while
  // another's is on its way.
  const [profileAnswer, setProfileAnswer] = useState<{ type: string; object: string; value?: ObjectProfile; notFound?: boolean; failed?: string } | null>(null);
  // Asks for the open object's profile again: its row clicked while it is open, Refresh, or an
  // action that changed it. The URL does not change, so nothing else would.
  const [profileAsk, setProfileAsk] = useState(0);
  const [activeAction, setActiveAction] = useState<ExplorerAction | null>(null);
  const [actionParams, setActionParams] = useState<Record<string, string>>({});
  const [actionResult, setActionResult] = useState<ActionResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const runQuery = useCallback(async (typeId = objectTypeId, nextFilters = filters, nextSearch = search) => {
    if (!typeId) return;
    const seq = ++querySeq.current;
    setLoading(true);
    setError("");
    try {
      const result = await queryObjects({ object_type_id: typeId, query: nextSearch, filters: nextFilters, selected_ids: selectedIds, limit: 500 });
      if (seq !== querySeq.current) return;
      setQuery(result);
      setSelectedIds((ids) => ids.filter((id) => result.objects.some((object) => object.id === id)));
      try {
        const evaluated = await evaluateRisk(typeId, result.objects.map((object) => object.id));
        if (seq === querySeq.current) setRisk(Object.fromEntries(evaluated.findings.map((finding) => [finding.object_id, finding.risk])));
      } catch {
        if (seq === querySeq.current) setRisk({});
      }
    } catch (cause) {
      if (seq === querySeq.current) setError(cause instanceof Error ? cause.message : "Object query failed");
    } finally {
      if (seq === querySeq.current) setLoading(false);
    }
  }, [filters, objectTypeId, search, selectedIds]);

  // With no type named, the first, adopted and never written.
  const routeType = route.type || types[0]?.id || "";
  const typeUnknown = typesLoaded && route.type !== "" && !types.some((type) => type.id === route.type);
  // The query shown answers the URL's type, or nothing does.
  const query = loadedQuery && loadedQuery.object_type_id === routeType && !typeUnknown ? loadedQuery : null;
  const answered = profileAnswer && profileAnswer.type === routeType && profileAnswer.object === route.object ? profileAnswer : null;
  const profile = route.object && !typeUnknown ? answered?.value ?? null : null;
  // Named only once the types are known: under an unknown type, the type is what is unknown.
  const objectMissing = typesLoaded && !typeUnknown && route.object !== "" && Boolean(answered?.notFound);

  useEffect(() => {
    Promise.all([listObjectTypes(), listExplorations()]).then(([nextTypes, saved]) => {
      setTypes(nextTypes);
      setExplorations(saved);
      setTypesLoaded(true);
      if (!nextTypes.length) setLoading(false);
    }).catch((cause) => {
      setError(cause instanceof Error ? cause.message : "Object Explorer failed to load");
      setLoading(false);
    });
  }, []);

  // The URL's type drives the query. A type chosen here, by Back or by a link, starts with no
  // filters and nothing selected; a saved exploration sets its own before its URL, so it keeps
  // them.
  useEffect(() => {
    if (!typesLoaded || routeType === objectTypeId) return;
    setObjectTypeId(routeType);
    setFilters({});
    setSelectedIds([]);
    // An action, its result and a notice were about the last type's objects.
    setActiveAction(null);
    setActionParams({});
    setActionResult(null);
    setNotice("");
    if (typeUnknown || !routeType) {
      querySeq.current += 1;
      setQuery(null);
      setLoading(false);
      return;
    }
    void runQuery(routeType, {}, search);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typesLoaded, routeType]);

  // The object inspected is the URL's, and its own 404 names it, never its absence from a
  // filtered result.
  useEffect(() => {
    if (!route.object || !routeType || typeUnknown) return undefined;
    let cancelled = false;
    const type = routeType;
    const object = route.object;
    getObjectProfile(type, object).then(
      (next) => { if (!cancelled) setProfileAnswer({ type, object, value: next }); },
      (cause: unknown) => {
        if (cancelled) return;
        // Kept on the answer, so it shows only while the URL names this object.
        if (isNotFound(cause)) setProfileAnswer({ type, object, notFound: true });
        else setProfileAnswer({ type, object, failed: cause instanceof Error ? cause.message : "Object profile failed to load" });
      });
    return () => {
      cancelled = true;
    };
  }, [routeType, route.object, typeUnknown, profileAsk]);

  const selectObject = (object: ObjectRecord) => {
    setSelectedIds((ids) => ids.includes(object.id) ? ids : [...ids, object.id]);
    setError("");
    // The row and its link both call this; the second is the URL already open and adds nothing.
    // The object already open is asked for again, as a click on it always did.
    if (object.id === route.object) setProfileAsk((count) => count + 1);
    else navigate("object-explorer", { type: routeType, object: object.id });
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
    // In the same batch, so the type's effect finds the type already open and keeps these filters.
    navigate("object-explorer", { type: saved.object_type_id });
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
      if (route.object && result.mutated_object_ids.includes(route.object)) setProfileAsk((count) => count + 1);
      setNotice(result.message);
      setActiveAction(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Action execution failed");
    }
  };

  const columns = query?.columns.slice(0, 8) || [];
  const selectedType = types.find((type) => type.id === routeType);
  // Values are drawn by the type the ontology declares for them. The query's
  // object type carries the property declarations, so a geoshape renders as a
  // shape and a timestamp in the viewer's zone without this component knowing
  // which object types exist.
  const specs = propertySpecs(
    (query?.object_type?.properties || selectedType?.properties) as Record<string, unknown> | undefined,
  );

  return (
    <Page title="Object Explorer" subtitle="Search ontology objects, filter with live facets, inspect relationships, and run governed actions.">
      <div className="explorer-command-bar">
        <label><span>Object type</span><select aria-label="Object type" value={routeType} onChange={(event) => navigate("object-explorer", { type: event.target.value })}>{typeUnknown ? <option value={route.type} disabled>{`Unknown: ${route.type}`}</option> : null}{types.map((type) => <option key={type.id} value={type.id}>{type.display_name}</option>)}</select></label>
        <label className="explorer-search"><Search size={16} /><input aria-label="Search objects" value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !typeUnknown) void runQuery(); }} placeholder="Search objects and properties" /></label>
        <button className="primary" onClick={() => void runQuery()} disabled={typeUnknown}><Play size={15} />Run</button>
        <button onClick={() => void persistExploration()} disabled={!query}><BookmarkPlus size={15} />Save view</button>
        <button aria-label="Refresh exploration" title="Refresh" onClick={() => { void runQuery(); setProfileAsk((count) => count + 1); }} disabled={typeUnknown}><RefreshCw size={15} /></button>
      </div>
      <ErrorBanner message={error} />
      {notice ? <div className="inline-success" role="status">{notice}</div> : null}
      <div className="explorer-layout">
        <aside className="explorer-left-rail">
          <Panel title="Saved Explorations">
            <div className="explorer-saved-list">{explorations.map((saved) => <button key={saved.id} onClick={() => openExploration(saved)}><span><strong>{saved.display_name}</strong><small>{saved.object_type_id}</small></span><ChevronRight size={14} /></button>)}</div>
            {!explorations.length ? <EmptyState inline>Save a query to return to it later.</EmptyState> : null}
          </Panel>
          <Panel title="Filters" action={<Filter size={15} />}>
            <div className="filter-chip-list">{Object.entries(filters).map(([field, value]) => <button key={field} onClick={() => { const next = { ...filters }; delete next[field]; setFilters(next); void runQuery(objectTypeId, next, search); }} title="Remove filter"><span>{field}: {filterLabel(value)}</span><X size={12} /></button>)}</div>
            {!Object.keys(filters).length ? <EmptyState inline compact>Select a facet value to filter results.</EmptyState> : null}
          </Panel>
          <div className="facet-stack">{query?.facets.map((facet) => <FacetCard key={`${query.object_type_id}:${facet.field}`} facet={facet} onApply={(value) => applyFacet(facet, value)} />)}</div>
        </aside>

        <main className="explorer-results-panel">
          <header className="explorer-results-header"><div><h2>{query?.object_type?.display_name || selectedType?.display_name || "Objects"}</h2><span>{query ? `${query.result_count} results across ${columns.length} visible fields` : "Run an exploration"}</span></div><StatusBadge value={selectedIds.length ? `${selectedIds.length} selected` : "ready"} intent="neutral" /></header>
          {typeUnknown ? <UnknownResource noun="object type" id={route.type} /> : null}
          {loading && !typeUnknown ? <LoadingState label="Evaluating object set and risk..." /> : null}
          {!loading && !typeUnknown && !query?.objects.length ? <EmptyState title="No matching objects" description="Change the object type, search phrase, or active facet filters." /> : null}
          {!loading && !typeUnknown && query?.objects.length ? <div className="table-wrap explorer-table" tabIndex={0}><table>{query.columns.length > columns.length ? <caption className="table-truncated">Showing {columns.length} of {query.columns.length} columns</caption> : null}<thead><tr><th className="selection-cell"><input aria-label="Select all objects" type="checkbox" checked={selectedIds.length === query.objects.length} onChange={(event) => setSelectedIds(event.target.checked ? query.objects.map((object) => object.id) : [])} /></th><th>Object</th><th>Risk</th>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{query.objects.map((object) => <tr key={object.id} className={profile?.object.id === object.id ? "selected" : ""} onClick={() => void selectObject(object)}><td className="selection-cell" onClick={(event) => event.stopPropagation()}><input aria-label={`Select ${object.id}`} type="checkbox" checked={selectedIds.includes(object.id)} onChange={(event) => setSelectedIds((ids) => event.target.checked ? [...new Set([...ids, object.id])] : ids.filter((id) => id !== object.id))} /></td><td><button className="object-link" onClick={() => void selectObject(object)}>{object.id}</button></td><td><StatusBadge value={risk[object.id] ? `${risk[object.id].band} ${risk[object.id].score}` : "not scored"} intent={intentOf(RISK_BAND, risk[object.id] ? risk[object.id].band : "not scored")} /></td>{columns.map((column) => <td key={column} title={formatValue(propertyValue(object, column))}>{renderPropertyValue(propertyValue(object, column), specs[column])}</td>)}</tr>)}</tbody></table></div> : null}
        </main>

        <aside className="explorer-inspector" tabIndex={0} aria-label="Object inspector">
          <Panel title="Object Preview" action={<Network size={15} />}>
            {objectMissing ? <UnknownResource scope={selectedType?.display_name || routeType} noun="object" id={route.object} /> : answered?.failed && route.object && !typeUnknown ? <ErrorBanner message={answered.failed} /> : !profile ? <EmptyState inline>Select a result to inspect its properties and links.</EmptyState> : <><header className="object-profile-heading"><div><strong>{formatValue(profile.object.properties.name || profile.object.properties.title || profile.object.id)}</strong><small>{profile.object.id}</small></div><StatusBadge value={risk[profile.object.id]?.band || "unscored"} intent={intentOf(RISK_BAND, risk[profile.object.id]?.band || "unscored")} /></header><KeyValueGrid data={profile.object.properties} specs={specs} /><div className="object-profile-metrics"><span>{profile.inbound_links.length} inbound</span><span>{profile.outbound_links.length} outbound</span><span>{profile.linked_objects.length} linked</span></div>{risk[profile.object.id]?.explanation ? <p className="risk-explanation"><ShieldCheck size={15} />{risk[profile.object.id].explanation}</p> : null}</>}
          </Panel>
          <Panel title="Governed Actions">
            {!query?.available_actions.length ? <EmptyState inline>No actions are bound to this object type.</EmptyState> : <div className="explorer-action-list">{query.available_actions.map((action) => <button key={action.id} disabled={!selectedIds.length} onClick={() => { setActiveAction(action); setActionParams({}); }}><span><strong>{action.display_name}</strong><small>{action.description || `${action.id} action`}</small></span><ChevronRight size={14} /></button>)}</div>}
            {actionResult ? <div className="action-result"><StatusBadge value={actionResult.status} intent={intentOf(ACTION_RESULT, actionResult.status)} /><span>{actionResult.approval_request_id ? `Approval ${actionResult.approval_request_id}` : actionResult.message}</span></div> : null}
          </Panel>
        </aside>
      </div>
      {activeAction ? <Dialog className="action-modal" labelledBy="bulk-action-title" onClose={() => setActiveAction(null)}><header><div><h2 id="bulk-action-title">{activeAction.display_name}</h2><p>{selectedIds.length} selected object{selectedIds.length === 1 ? "" : "s"}</p></div><button aria-label="Close action" onClick={() => setActiveAction(null)}><X size={16} /></button></header>{parameterNames(activeAction).filter((name) => name !== "object_id").map((name) => <label key={name}><span>{name.replace(/_/g, " ")}</span><input value={actionParams[name] || ""} onChange={(event) => setActionParams((values) => ({ ...values, [name]: event.target.value }))} /></label>)}<div className="button-row"><button onClick={() => setActiveAction(null)}>Cancel</button><button className="primary" onClick={() => void runAction()}><ShieldCheck size={15} />Evaluate and run</button></div></Dialog> : null}
    </Page>
  );
}
