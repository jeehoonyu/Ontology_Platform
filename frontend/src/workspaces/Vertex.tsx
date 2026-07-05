import { useEffect, useState } from "react";
import {
  createVertexGraph,
  exploreVertexGraph,
  filterVertexGraph,
  getVertexGraph,
  layoutVertexGraph,
  listLinkTypes,
  listObjectTypes,
  listObjects,
  listVertexGraphs,
  mergeVertexLinks,
  VERTEX_AGGREGATIONS,
  VERTEX_DIRECTIONS,
  VERTEX_FILTER_OPS,
  VERTEX_LAYOUTS
} from "../api/vertexApi";
import type {
  VertexAggregation,
  VertexDirection,
  VertexFilterOp,
  VertexGraph,
  VertexLayout,
  VertexLinkType,
  VertexObjectInstance,
  VertexObjectType
} from "../api/vertexApi";
import {
  DataTable,
  DeveloperEvidence,
  EmptyState,
  ErrorBanner,
  KeyValueGrid,
  LoadingState,
  Metric,
  Panel,
  StatusBadge
} from "../components/data/DataDisplay";
import { MiniGraph } from "../components/canvas/PipelineCanvas";
import { Page } from "../components/workbench/Workbench";
import { useAsyncState } from "../hooks/useAsyncState";
import { asString, classNames } from "../utils/format";
import type { JsonValue, TableRow } from "../types";

function parseSeedIds(raw: string): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const part of raw.split(",")) {
    const id = part.trim();
    if (id && !seen.has(id)) {
      seen.add(id);
      result.push(id);
    }
  }
  return result;
}

// Coerce a free-text filter value into the closest JSON scalar so it compares
// correctly against typed node properties on the backend.
function coerceFilterValue(raw: string): JsonValue {
  const trimmed = raw.trim();
  if (trimmed === "") return "";
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  if (trimmed === "null") return null;
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return Number(trimmed);
  return trimmed;
}

// MiniGraph reads id/kind/type/label on nodes and source/target on edges — map
// the Vertex node/edge dicts (object_type_id, source_object_id, ...) onto them.
function toGraphNodes(graph: VertexGraph | null): TableRow[] {
  return (graph?.nodes || []).map((node) => ({
    id: node.id,
    type: node.object_type_id,
    label: node.object_type_id ? `${node.object_type_id}: ${node.id}` : node.id,
    is_seed: node.is_seed ?? false,
    faded: node.faded ?? false
  }));
}

function toGraphEdges(graph: VertexGraph | null): TableRow[] {
  return (graph?.edges || []).map((edge, index) => ({
    id: asString(edge.id, `edge-${index}`),
    source: edge.source_object_id,
    target: edge.target_object_id,
    link_type_id: edge.link_type_id ?? "",
    count: edge.merged_count ?? "",
    weight: edge.merged_weight ?? ""
  }));
}

export function Vertex() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedGraphId, setSelectedGraphId] = useState("");
  const [graph, setGraph] = useState<VertexGraph | null>(null);
  const [status, setStatus] = useState(
    "Create a graph from seed object ids, then expand, lay out, filter, and merge links."
  );
  const [actionError, setActionError] = useState("");

  // Create-graph form.
  const [displayName, setDisplayName] = useState("Vertex exploration");
  const [seedIdsText, setSeedIdsText] = useState("");
  const [createLayout, setCreateLayout] = useState<VertexLayout>("auto");
  const [seedObjectTypeId, setSeedObjectTypeId] = useState("");

  // Explore controls.
  const [exploreLinkTypeId, setExploreLinkTypeId] = useState("");
  const [direction, setDirection] = useState<VertexDirection>("both");
  const [depth, setDepth] = useState(1);

  // Filter controls.
  const [filterProperty, setFilterProperty] = useState("");
  const [filterOp, setFilterOp] = useState<VertexFilterOp>("eq");
  const [filterValue, setFilterValue] = useState("");

  // Merge controls.
  const [mergeLinkTypeId, setMergeLinkTypeId] = useState("");
  const [aggregation, setAggregation] = useState<VertexAggregation>("count");

  const graphs = useAsyncState<VertexGraph[]>(listVertexGraphs, [refreshKey]);
  const objectTypes = useAsyncState<VertexObjectType[]>(listObjectTypes, []);
  const linkTypes = useAsyncState<VertexLinkType[]>(listLinkTypes, []);
  const seedObjects = useAsyncState<VertexObjectInstance[]>(
    () => (seedObjectTypeId ? listObjects(seedObjectTypeId) : Promise.resolve([])),
    [seedObjectTypeId]
  );

  useEffect(() => {
    if (!selectedGraphId && graphs.value && graphs.value.length) {
      setSelectedGraphId(graphs.value[0].id);
    }
  }, [graphs.value, selectedGraphId]);

  useEffect(() => {
    if (!selectedGraphId) return;
    let cancelled = false;
    getVertexGraph(selectedGraphId)
      .then((next) => !cancelled && setGraph(next))
      .catch(() => !cancelled && setGraph(null));
    return () => {
      cancelled = true;
    };
  }, [selectedGraphId]);

  async function run(fn: () => Promise<void>) {
    try {
      setActionError("");
      await fn();
    } catch (err) {
      setActionError((err as Error).message);
    }
  }

  function addSeed(id: string) {
    setSeedIdsText((current) => {
      const ids = parseSeedIds(current);
      if (ids.includes(id)) return current;
      return [...ids, id].join(", ");
    });
  }

  async function createGraph() {
    const seeds = parseSeedIds(seedIdsText);
    if (!displayName.trim() || !seeds.length) {
      setActionError("A display name and at least one seed object id are required.");
      return;
    }
    await run(async () => {
      const next = await createVertexGraph({
        display_name: displayName.trim(),
        seed_object_ids: seeds,
        layout_type: createLayout
      });
      setGraph(next);
      setSelectedGraphId(next.id);
      setStatus(`Created graph "${next.display_name}" with ${next.nodes.length} seed node(s).`);
      setRefreshKey((key) => key + 1);
    });
  }

  async function explore() {
    if (!selectedGraphId) return;
    await run(async () => {
      const res = await exploreVertexGraph(selectedGraphId, {
        link_type_id: exploreLinkTypeId || undefined,
        direction,
        depth
      });
      setGraph(res.graph);
      setStatus(`Expanded (${direction}, depth ${depth}): +${res.added_nodes} node(s), +${res.added_edges} edge(s).`);
    });
  }

  async function changeLayout(next: VertexLayout) {
    if (!selectedGraphId) return;
    await run(async () => {
      const updated = await layoutVertexGraph(selectedGraphId, next);
      setGraph(updated);
      setStatus(`Layout changed to "${updated.layout_type}".`);
    });
  }

  async function applyFilter() {
    if (!selectedGraphId || !filterProperty.trim()) {
      setActionError("A property name is required to filter.");
      return;
    }
    await run(async () => {
      const res = await filterVertexGraph(selectedGraphId, {
        property: filterProperty.trim(),
        op: filterOp,
        value: coerceFilterValue(filterValue)
      });
      setGraph(res.graph);
      setStatus(`Filter "${filterProperty} ${filterOp}": ${res.matched} matched, ${res.faded} faded.`);
    });
  }

  async function mergeLinks() {
    if (!selectedGraphId) return;
    await run(async () => {
      const res = await mergeVertexLinks(selectedGraphId, {
        link_type_id: mergeLinkTypeId || undefined,
        aggregation
      });
      setGraph(res.graph);
      setStatus(
        `Merged ${res.merged_edge_count} group(s) with ${aggregation}: ${res.before_edge_count} → ${res.after_edge_count} edge(s).`
      );
    });
  }

  const nodes = graph?.nodes || [];
  const edges = graph?.edges || [];
  const seedCount = graph?.seed_object_ids.length ?? 0;
  const parsedSeeds = parseSeedIds(seedIdsText);

  return (
    <Page title="Vertex Graph Explorer" subtitle="Build graphs from seed objects, then expand, lay out, filter, and merge links.">
      <ErrorBanner message={actionError || graphs.error} />
      {graphs.loading && !graphs.value ? <LoadingState label="Loading Vertex graphs..." /> : null}
      <div className="notice">{status}</div>

      <div className="grid metrics">
        <Metric label="Nodes" value={nodes.length} />
        <Metric label="Edges" value={edges.length} />
        <Metric label="Seeds" value={seedCount} />
        <Metric label="Layout" value={graph?.layout_type || "-"} />
      </div>

      <div className="two-col">
        <Panel title="Create Graph" action={<button onClick={createGraph}>Create graph</button>}>
          <div className="metadata-edit-grid">
            <label>
              <span>Display name</span>
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Vertex exploration" />
            </label>
            <label>
              <span>Seed object ids (comma-separated)</span>
              <textarea
                value={seedIdsText}
                onChange={(event) => setSeedIdsText(event.target.value)}
                placeholder="asset_react_1, asset_react_2"
              />
            </label>
            <label>
              <span>Initial layout</span>
              <select value={createLayout} onChange={(event) => setCreateLayout(event.target.value as VertexLayout)}>
                {VERTEX_LAYOUTS.map((layout) => (
                  <option key={layout} value={layout}>{layout}</option>
                ))}
              </select>
            </label>
            <div className="button-row">
              <span>{parsedSeeds.length} seed id(s) parsed</span>
              <button onClick={() => setSeedIdsText("")} disabled={!seedIdsText}>Clear seeds</button>
            </div>
          </div>
          <div className="section-card-grid">
            <label>
              <span>Seed from object type</span>
              <select value={seedObjectTypeId} onChange={(event) => setSeedObjectTypeId(event.target.value)}>
                <option value="">Choose object type</option>
                {(objectTypes.value || []).map((objectType) => (
                  <option key={objectType.id} value={objectType.id}>{objectType.display_name || objectType.id}</option>
                ))}
              </select>
            </label>
          </div>
          {seedObjectTypeId ? (
            <div className="button-row">
              {seedObjects.loading ? <span>Loading objects...</span> : null}
              {(seedObjects.value || []).slice(0, 24).map((object) => (
                <button key={object.id} onClick={() => addSeed(object.id)} title={`Add ${object.id} to seeds`}>
                  + {object.id}
                </button>
              ))}
              {!seedObjects.loading && !(seedObjects.value || []).length ? (
                <span>No objects for this type.</span>
              ) : null}
            </div>
          ) : null}
        </Panel>

        <Panel title="Graphs" action={<button onClick={() => setRefreshKey((key) => key + 1)}>Refresh</button>}>
          {graphs.value && graphs.value.length ? (
            <div className="button-row">
              {graphs.value.map((item) => (
                <button
                  key={item.id}
                  className={classNames(selectedGraphId === item.id && "active")}
                  onClick={() => setSelectedGraphId(item.id)}
                >
                  <strong>{item.display_name}</strong>
                  <span>{item.nodes.length}n / {item.edges.length}e</span>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState title="No graphs yet" description="Create a graph from seed object ids to begin exploring." />
          )}
        </Panel>
      </div>

      <Panel title={graph ? `Graph: ${graph.display_name}` : "Graph Explorer"}>
        {graph ? (
          nodes.length ? (
            <MiniGraph nodes={toGraphNodes(graph)} edges={toGraphEdges(graph)} />
          ) : (
            <EmptyState title="Empty graph" description="Expand from the seeds using the Explore controls below." />
          )
        ) : (
          <EmptyState title="No graph selected" description="Create or select a graph to render its nodes and edges." />
        )}
      </Panel>

      <div className="two-col">
        <Panel title="Explore / Expand" action={<button onClick={explore} disabled={!selectedGraphId}>Expand</button>}>
          <div className="metadata-edit-grid">
            <label>
              <span>Link type (optional)</span>
              <select value={exploreLinkTypeId} onChange={(event) => setExploreLinkTypeId(event.target.value)}>
                <option value="">All link types</option>
                {(linkTypes.value || []).map((linkType) => (
                  <option key={linkType.id} value={linkType.id}>{linkType.display_name || linkType.id}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Direction</span>
              <select value={direction} onChange={(event) => setDirection(event.target.value as VertexDirection)}>
                {VERTEX_DIRECTIONS.map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Depth</span>
              <input
                type="number"
                min={1}
                max={6}
                value={depth}
                onChange={(event) => setDepth(Math.max(1, Math.min(6, Number(event.target.value) || 1)))}
              />
            </label>
          </div>
        </Panel>

        <Panel title="Layout">
          <div className="button-row">
            {VERTEX_LAYOUTS.map((layout) => (
              <button
                key={layout}
                className={classNames(graph?.layout_type === layout && "active")}
                onClick={() => changeLayout(layout)}
                disabled={!selectedGraphId}
              >
                {layout}
              </button>
            ))}
          </div>
        </Panel>
      </div>

      <div className="two-col">
        <Panel title="Filter (fade non-matching)" action={<button onClick={applyFilter} disabled={!selectedGraphId}>Apply filter</button>}>
          <div className="metadata-edit-grid">
            <label>
              <span>Property</span>
              <input value={filterProperty} onChange={(event) => setFilterProperty(event.target.value)} placeholder="status" />
            </label>
            <label>
              <span>Operator</span>
              <select value={filterOp} onChange={(event) => setFilterOp(event.target.value as VertexFilterOp)}>
                {VERTEX_FILTER_OPS.map((op) => (
                  <option key={op} value={op}>{op}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Value</span>
              <input
                value={filterValue}
                onChange={(event) => setFilterValue(event.target.value)}
                placeholder="DEGRADED"
                disabled={filterOp === "exists"}
              />
            </label>
          </div>
        </Panel>

        <Panel title="Merge Links" action={<button onClick={mergeLinks} disabled={!selectedGraphId}>Merge links</button>}>
          <div className="metadata-edit-grid">
            <label>
              <span>Link type (optional)</span>
              <select value={mergeLinkTypeId} onChange={(event) => setMergeLinkTypeId(event.target.value)}>
                <option value="">All link types</option>
                {(linkTypes.value || []).map((linkType) => (
                  <option key={linkType.id} value={linkType.id}>{linkType.display_name || linkType.id}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Aggregation</span>
              <select value={aggregation} onChange={(event) => setAggregation(event.target.value as VertexAggregation)}>
                {VERTEX_AGGREGATIONS.map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>
          </div>
        </Panel>
      </div>

      <div className="two-col">
        <Panel title={`Nodes (${nodes.length})`}>
          <DataTable rows={toGraphNodes(graph)} empty="No nodes in this graph yet." />
        </Panel>
        <Panel title={`Edges (${edges.length})`}>
          <DataTable rows={toGraphEdges(graph)} empty="No edges yet — expand the graph to traverse links." />
        </Panel>
      </div>

      {graph ? (
        <DeveloperEvidence title="Developer evidence: graph summary">
          <KeyValueGrid
            data={{
              id: graph.id,
              display_name: graph.display_name,
              layout_type: graph.layout_type,
              seed_object_ids: graph.seed_object_ids.join(", "),
              node_count: nodes.length,
              edge_count: edges.length,
              updated_at: graph.updated_at
            }}
          />
          <div className="manager-chip-row">
            <StatusBadge value={`${nodes.filter((node) => node.faded).length} faded`} />
            <StatusBadge value={`${edges.filter((edge) => edge.merged).length} merged`} />
          </div>
        </DeveloperEvidence>
      ) : null}
    </Page>
  );
}
