import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  applyNodeChanges,
  type Edge,
  type Node,
  type NodeChange
} from "@xyflow/react";
import { Expand, LocateFixed, Save, Search } from "lucide-react";
import { api } from "../api";
import { EmptyState, ErrorBanner, KeyValueGrid, LoadingState, Panel, StatusBadge } from "../components/data/DataDisplay";
import { Page } from "../components/workbench/Workbench";
import { useAsyncState } from "../hooks/useAsyncState";
import { asString } from "../utils/format";
import type { JsonObject, TableRow } from "../types";

interface GraphOverview {
  node_count: number;
  edge_count: number;
  summary: Record<string, number>;
  nodes: TableRow[];
  edges: TableRow[];
}

const KIND_COLORS: Record<string, string> = {
  dataset: "#607d8b",
  pipeline: "#2386a8",
  object_type: "#7c5aa6",
  object: "#2d8b69",
  incident: "#b44f4f",
  model: "#b58018",
  monitor: "#68737d",
  report: "#496cb0"
};

function layoutNodes(rows: TableRow[]): Node<JsonObject>[] {
  const counters: Record<string, number> = {};
  const kinds = Array.from(new Set(rows.map((row) => asString(row.kind, "resource"))));
  return rows.map((row) => {
    const kind = asString(row.kind, "resource");
    const index = counters[kind] || 0;
    counters[kind] = index + 1;
    return {
      id: asString(row.id),
      position: { x: kinds.indexOf(kind) * 270, y: index * 92 },
      data: { ...row, label: asString(row.label || row.resource_id || row.id) },
      style: { borderColor: KIND_COLORS[kind] || "#77838d" },
      className: `platform-graph-node kind-${kind}`
    };
  });
}

export function PlatformGraphWorkspace() {
  const graph = useAsyncState<GraphOverview>(() => api<GraphOverview>("/graph/overview?limit=500"), []);
  const [nodes, setNodes] = useState<Node<JsonObject>[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [visibleKinds, setVisibleKinds] = useState<Set<string>>(new Set());
  const [neighborhoodOnly, setNeighborhoodOnly] = useState(false);

  useEffect(() => {
    if (!graph.value) return;
    const nextNodes = layoutNodes(graph.value.nodes || []);
    const saved = localStorage.getItem("ontology.platformGraph.layout");
    if (saved) {
      try {
        const positions = JSON.parse(saved) as Record<string, { x: number; y: number }>;
        nextNodes.forEach((node) => { if (positions[node.id]) node.position = positions[node.id]; });
      } catch { /* Ignore an invalid local view and use deterministic layout. */ }
    }
    setNodes(nextNodes);
    setVisibleKinds(new Set(Object.keys(graph.value.summary || {})));
  }, [graph.value]);

  const edges = useMemo<Edge[]>(() => (graph.value?.edges || []).map((row, index) => ({
    id: asString(row.id, `edge-${index}`),
    source: asString(row.source || row.source_id),
    target: asString(row.target || row.target_id),
    label: asString(row.label || row.kind),
    type: "smoothstep"
  })), [graph.value]);

  const neighborIds = useMemo(() => {
    const result = new Set<string>(selectedId ? [selectedId] : []);
    edges.forEach((edge) => {
      if (edge.source === selectedId) result.add(edge.target);
      if (edge.target === selectedId) result.add(edge.source);
    });
    return result;
  }, [edges, selectedId]);

  const visibleNodes = useMemo(() => nodes.filter((node) => {
    const kind = asString(node.data.kind, "resource");
    const matchesKind = visibleKinds.has(kind);
    const haystack = `${node.id} ${asString(node.data.label)} ${kind}`.toLowerCase();
    return matchesKind && haystack.includes(query.toLowerCase()) && (!neighborhoodOnly || !selectedId || neighborIds.has(node.id));
  }), [nodes, visibleKinds, query, neighborhoodOnly, selectedId, neighborIds]);
  const visibleIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleEdges = useMemo(() => edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)), [edges, visibleIds]);
  const selected = nodes.find((node) => node.id === selectedId);

  const onNodesChange = useCallback((changes: NodeChange<Node<JsonObject>>[]) => {
    setNodes((current) => applyNodeChanges(changes, current));
  }, []);

  function toggleKind(kind: string) {
    setVisibleKinds((current) => {
      const next = new Set(current);
      if (next.has(kind)) next.delete(kind); else next.add(kind);
      return next;
    });
  }

  function autoLayout() {
    setNodes((current) => {
      const positions = new Map(layoutNodes(current.map((node) => node.data as TableRow)).map((node) => [node.id, node.position]));
      return current.map((node) => ({ ...node, position: positions.get(node.id) || node.position }));
    });
  }

  function saveView() {
    localStorage.setItem("ontology.platformGraph.layout", JSON.stringify(Object.fromEntries(nodes.map((node) => [node.id, node.position]))));
  }

  return (
    <Page title="Platform Graph" subtitle="Explore operational resources, move nodes, expand neighborhoods, and inspect evidence relationships.">
      <ErrorBanner message={graph.error} />
      {graph.loading ? <LoadingState label="Loading platform graph..." /> : null}
      <div className="platform-graph-toolbar" role="toolbar" aria-label="Platform graph controls">
        <label className="graph-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search nodes" /></label>
        <button onClick={() => setNeighborhoodOnly((value) => !value)} disabled={!selectedId}><Expand size={15} />{neighborhoodOnly ? "Show all" : "Neighbors"}</button>
        <button onClick={autoLayout}><LocateFixed size={15} />Auto layout</button>
        <button onClick={saveView}><Save size={15} />Save view</button>
        <span>{visibleNodes.length} nodes / {visibleEdges.length} edges</span>
      </div>
      <div className="platform-graph-kinds" aria-label="Resource type filters">
        {Object.entries(graph.value?.summary || {}).map(([kind, count]) => (
          <button key={kind} className={visibleKinds.has(kind) ? "active" : ""} onClick={() => toggleKind(kind)}>
            <span style={{ background: KIND_COLORS[kind] || "#77838d" }} />{kind.replace(/_/g, " ")} <small>{count}</small>
          </button>
        ))}
      </div>
      <div className="platform-graph-layout">
        <section className="platform-graph-canvas" aria-label="Interactive platform graph">
          {visibleNodes.length ? (
            <ReactFlow
              nodes={visibleNodes}
              edges={visibleEdges}
              onNodesChange={onNodesChange}
              onNodeClick={(_, node) => setSelectedId(node.id)}
              nodesDraggable
              nodesConnectable={false}
              fitView
              minZoom={0.15}
              maxZoom={2}
            >
              <Background gap={24} color="#d5dce0" />
              <MiniMap pannable zoomable nodeColor={(node) => KIND_COLORS[asString(node.data?.kind)] || "#77838d"} />
              <Controls showInteractive={false} />
            </ReactFlow>
          ) : <EmptyState title="No graph nodes match" description="Clear search text or enable another resource type." />}
        </section>
        <Panel title="Selected Resource">
          {selected ? (
            <div className="graph-detail-drawer">
              <div><StatusBadge value={asString(selected.data.kind)} /><strong>{asString(selected.data.label)}</strong></div>
              <KeyValueGrid data={selected.data} />
              <h3>Connections</h3>
              {(edges.filter((edge) => edge.source === selected.id || edge.target === selected.id)).map((edge) => (
                <button key={edge.id} onClick={() => setSelectedId(edge.source === selected.id ? edge.target : edge.source)}>{edge.label || "related"}</button>
              ))}
            </div>
          ) : <EmptyState title="Select a node" description="Choose a graph node to inspect its metadata and connections." />}
        </Panel>
      </div>
    </Page>
  );
}
