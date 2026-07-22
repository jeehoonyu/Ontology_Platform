import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type ReactFlowInstance
} from "@xyflow/react";
import {
  Archive,
  Check,
  Copy,
  History,
  Plus,
  Redo2,
  Save,
  Search,
  Send,
  Trash2,
  Undo2
} from "lucide-react";
import { DndContext, closestCenter, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, verticalListSortingStrategy, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  acquireArtifactLease,
  createArtifact,
  listArtifacts,
  listArtifactVersions,
  publishArtifact,
  restoreArtifactVersion,
  saveArtifact,
  type ArtifactLease,
  type ArtifactNodeData,
  type ArtifactState,
  type ArtifactType,
  type PlatformArtifact
} from "../api/artifactApi";
import { EmptyState, ErrorBanner, LoadingState, StatusBadge } from "../components/data/DataDisplay";

interface VisualBuilderProps {
  artifactType: ArtifactType;
  title: string;
  subtitle: string;
}

const LIBRARIES: Record<ArtifactType, Array<{ type: string; label: string; description: string }>> = {
  pipeline: [],
  ontology: [],
  workshop: [
    ["object_table", "Object table", "Browse and select ontology objects"],
    ["metric", "Metric", "Show an operational KPI"],
    ["chart", "Chart", "Visualize grouped or time-series data"],
    ["map", "Map", "Display geometry and operational layers"],
    ["graph", "Graph", "Explore linked objects"],
    ["timeline", "Timeline", "Show temporal object activity"],
    ["filter", "Filter", "Control object or dataset filters"],
    ["form", "Form", "Collect typed user input"],
    ["action", "Action", "Run a governed ontology action"],
    ["risk", "Risk panel", "Explain decision score drivers"],
    ["aip_assist", "AIP Assist", "Provide contextual recommendations"]
  ].map(([type, label, description]) => ({ type, label, description })),
  aip_logic: [
    ["object_query", "Query objects", "Load ontology context"],
    ["function", "Function", "Run deterministic platform logic"],
    ["model", "Model", "Invoke a governed model deployment"],
    ["risk", "Score risk", "Evaluate a decision scorecard"],
    ["scenario", "Run scenario", "Compare before and after impact"],
    ["branch", "Branch", "Route execution from a condition"],
    ["alert", "Create alert", "Evaluate and stage an alert"],
    ["incident", "Create incident", "Open an operational incident"],
    ["runbook", "Run runbook", "Execute deterministic response steps"],
    ["approval", "Request approval", "Pause for human review"],
    ["action", "Propose action", "Stage a governed object mutation"]
  ].map(([type, label, description]) => ({ type, label, description })),
  investigation_graph: [
    ["entity", "Entity", "Pin an ontology object"],
    ["evidence", "Evidence", "Attach a source or observation"],
    ["hypothesis", "Hypothesis", "Track a testable explanation"],
    ["finding", "Finding", "Record a supported conclusion"],
    ["timeline", "Timeline", "Add a temporal evidence lane"],
    ["report", "Report", "Generate an investigation narrative"]
  ].map(([type, label, description]) => ({ type, label, description })),
  platform_graph: [
    ["dataset", "Dataset", "Data asset or import output"],
    ["pipeline", "Pipeline", "Transformation and delivery graph"],
    ["object_type", "Object type", "Ontology semantic type"],
    ["action", "Action", "Governed operational mutation"],
    ["incident", "Incident", "Operational response record"],
    ["model", "Model", "Model objective or deployment"],
    ["report", "Report", "Published evidence artifact"]
  ].map(([type, label, description]) => ({ type, label, description })),
  entity_resolution: [
    ["source", "Source entity", "Entity selected for resolution"],
    ["candidate", "Candidate", "Potential duplicate entity"],
    ["comparison", "Comparison", "Field-level similarity review"],
    ["confidence", "Confidence", "Explain matching score drivers"],
    ["review", "Review gate", "Accept or reject a candidate"],
    ["merge", "Merge", "Stage a governed merge"],
    ["split", "Split", "Restore a merged entity"]
  ].map(([type, label, description]) => ({ type, label, description }))
};

function stateNodes(artifact: PlatformArtifact | undefined): Node<ArtifactNodeData>[] {
  return (artifact?.state?.nodes || []) as Node<ArtifactNodeData>[];
}

function stateEdges(artifact: PlatformArtifact | undefined): Edge[] {
  return (artifact?.state?.edges || []) as Edge[];
}

export function VisualBuilder({ artifactType, title, subtitle }: VisualBuilderProps) {
  const queryClient = useQueryClient();
  const artifacts = useQuery({ queryKey: ["artifacts", artifactType], queryFn: () => listArtifacts(artifactType) });
  const [selectedId, setSelectedId] = useState("");
  const artifact = useMemo(() => artifacts.data?.find((item) => item.id === selectedId) || artifacts.data?.[0], [artifacts.data, selectedId]);
  const [nodes, setNodes] = useState<Node<ArtifactNodeData>[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [lease, setLease] = useState<ArtifactLease | null>(null);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [instance, setInstance] = useState<ReactFlowInstance<Node<ArtifactNodeData>, Edge> | null>(null);
  const undoStack = useRef<Array<{ nodes: Node<ArtifactNodeData>[]; edges: Edge[] }>>([]);
  const redoStack = useRef<Array<{ nodes: Node<ArtifactNodeData>[]; edges: Edge[] }>>([]);
  const hydratedArtifact = useRef("");
  const library = (LIBRARIES[artifactType] || []).filter((item) => item.label.toLowerCase().includes(search.toLowerCase()));

  const versions = useQuery({
    queryKey: ["artifact-versions", artifact?.id],
    queryFn: () => listArtifactVersions(artifact!.id),
    enabled: Boolean(artifact)
  });

  useEffect(() => {
    if (!artifact || hydratedArtifact.current === `${artifact.id}:${artifact.current_revision}`) return;
    setNodes(stateNodes(artifact));
    setEdges(stateEdges(artifact));
    setDirty(false);
    setSelectedNodeId("");
    hydratedArtifact.current = `${artifact.id}:${artifact.current_revision}`;
  }, [artifact]);

  useEffect(() => {
    if (!artifact) return;
    acquireArtifactLease(artifact.id, lease?.artifact_id === artifact.id ? lease.token : undefined)
      .then(setLease)
      .catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
  }, [artifact?.id]);

  const createMutation = useMutation({
    mutationFn: () => createArtifact(artifactType, `${title} draft`),
    onSuccess: async (created) => {
      setSelectedId(created.id);
      await queryClient.invalidateQueries({ queryKey: ["artifacts", artifactType] });
    }
  });

  const saveMutation = useMutation({
    mutationFn: ({ reason }: { reason: string }) => {
      if (!artifact || !lease) throw new Error("Select an artifact and acquire its editing lease first.");
      return saveArtifact(artifact, { ...(artifact.state || {}), nodes: nodes as ArtifactState["nodes"], edges: edges as ArtifactState["edges"] }, lease.token, reason);
    },
    onSuccess: async (saved) => {
      setDirty(false);
      setMessage(`Saved revision ${saved.current_revision}`);
      hydratedArtifact.current = `${saved.id}:${saved.current_revision}`;
      queryClient.setQueryData<PlatformArtifact[]>(["artifacts", artifactType], (current = []) => current.map((item) => item.id === saved.id ? saved : item));
      await queryClient.invalidateQueries({ queryKey: ["artifact-versions", saved.id] });
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : String(error))
  });

  useEffect(() => {
    if (!dirty || !artifact || !lease || saveMutation.isPending) return;
    const timer = window.setTimeout(() => saveMutation.mutate({ reason: "Autosaved visual edit" }), 1200);
    return () => window.clearTimeout(timer);
  }, [dirty, nodes, edges, artifact?.id, artifact?.lock_version, lease?.token]);

  function snapshot() {
    undoStack.current.push({ nodes: structuredClone(nodes), edges: structuredClone(edges) });
    if (undoStack.current.length > 50) undoStack.current.shift();
    redoStack.current = [];
  }

  function changeNodes(changes: NodeChange<Node<ArtifactNodeData>>[]) {
    snapshot();
    setNodes((current) => applyNodeChanges(changes, current));
    setDirty(true);
  }

  function changeEdges(changes: EdgeChange<Edge>[]) {
    snapshot();
    setEdges((current) => applyEdgeChanges(changes, current));
    setDirty(true);
  }

  function connect(connection: Connection) {
    snapshot();
    setEdges((current) => addEdge({ ...connection, id: crypto.randomUUID() }, current));
    setDirty(true);
  }

  function addNode(nodeType: string, position?: { x: number; y: number }) {
    const item = LIBRARIES[artifactType].find((entry) => entry.type === nodeType);
    if (!item) return;
    snapshot();
    const id = `${nodeType}_${crypto.randomUUID().slice(0, 8)}`;
    setNodes((current) => [...current, {
      id,
      position: position || { x: 120 + current.length * 28, y: 100 + current.length * 28 },
      data: { label: item.label, description: item.description, nodeType, fields: [] },
      className: `visual-node visual-node-${nodeType}`
    }]);
    setSelectedNodeId(id);
    setDirty(true);
  }

  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const nodeType = event.dataTransfer.getData("application/ontology-builder-node");
    if (!nodeType || !instance) return;
    addNode(nodeType, instance.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
  }

  function undo() {
    const previous = undoStack.current.pop();
    if (!previous) return;
    redoStack.current.push({ nodes: structuredClone(nodes), edges: structuredClone(edges) });
    setNodes(previous.nodes);
    setEdges(previous.edges);
    setDirty(true);
  }

  function redo() {
    const next = redoStack.current.pop();
    if (!next) return;
    undoStack.current.push({ nodes: structuredClone(nodes), edges: structuredClone(edges) });
    setNodes(next.nodes);
    setEdges(next.edges);
    setDirty(true);
  }

  function updateSelected(data: ArtifactNodeData) {
    snapshot();
    setNodes((current) => current.map((node) => node.id === selectedNodeId ? { ...node, data } : node));
    setDirty(true);
  }

  const selectedNode = nodes.find((node) => node.id === selectedNodeId);

  if (artifacts.isLoading) return <LoadingState label={`Loading ${title} artifacts...`} />;
  if (artifacts.error) return <ErrorBanner message={artifacts.error instanceof Error ? artifacts.error.message : String(artifacts.error)} />;
  if (!artifact) return (
    <section className="visual-builder-empty">
      <EmptyState title={`No ${title} artifact`} description="Create a versioned draft to start building visually." />
      <button onClick={() => createMutation.mutate()} disabled={createMutation.isPending}><Plus size={16} /> Create draft</button>
    </section>
  );

  return (
    <section className="visual-builder-shell">
      <header className="visual-builder-header">
        <div>
          <span className="eyebrow">Visual builder</span>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        <div className="visual-builder-actions">
          <select aria-label={`${title} artifact`} value={artifact.id} onChange={(event) => setSelectedId(event.target.value)}>
            {(artifacts.data || []).map((item) => <option value={item.id} key={item.id}>{item.display_name}</option>)}
          </select>
          <StatusBadge value={dirty ? "UNSAVED" : saveMutation.isPending ? "SAVING" : artifact.status} />
          <button title="Undo" aria-label="Undo" onClick={undo} disabled={!undoStack.current.length}><Undo2 size={16} /></button>
          <button title="Redo" aria-label="Redo" onClick={redo} disabled={!redoStack.current.length}><Redo2 size={16} /></button>
          <button onClick={() => saveMutation.mutate({ reason: "Manual save" })} disabled={!dirty || saveMutation.isPending}><Save size={16} /> Save</button>
          <button className="primary-action" onClick={async () => {
            const saved = dirty ? await saveMutation.mutateAsync({ reason: "Save before publish" }) : null;
            const current = saved || (queryClient.getQueryData<PlatformArtifact[]>(["artifacts", artifactType]) || []).find((item) => item.id === artifact.id) || artifact;
            const published = await publishArtifact(current);
            queryClient.setQueryData<PlatformArtifact[]>(["artifacts", artifactType], (items = []) => items.map((item) => item.id === published.id ? published : item));
            setMessage(`Published revision ${published.current_revision}`);
          }}><Send size={16} /> Publish</button>
        </div>
      </header>
      {message ? <div className="operation-message" role="status">{message}<button aria-label="Dismiss message" onClick={() => setMessage("")}>×</button></div> : null}
      <div className="visual-builder-grid">
        <aside className="node-library-panel">
          <div className="search-field"><Search size={15} /><input aria-label="Search node library" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search tools" /></div>
          <div className="node-library-list">
            {library.map((item) => (
              <button
                key={item.type}
                draggable
                onDragStart={(event) => event.dataTransfer.setData("application/ontology-builder-node", item.type)}
                onClick={() => addNode(item.type)}
              >
                <Plus size={14} /><span><strong>{item.label}</strong><small>{item.description}</small></span>
              </button>
            ))}
          </div>
        </aside>
        <div className="visual-flow-canvas" onDrop={drop} onDragOver={(event) => event.preventDefault()}>
          <ReactFlow<Node<ArtifactNodeData>, Edge>
            nodes={nodes}
            edges={edges}
            onInit={setInstance}
            onNodesChange={changeNodes}
            onEdgesChange={changeEdges}
            onConnect={connect}
            onNodeClick={(_, node) => setSelectedNodeId(node.id)}
            onPaneClick={() => setSelectedNodeId("")}
            fitView
            snapToGrid
            snapGrid={[16, 16]}
            deleteKeyCode={["Backspace", "Delete"]}
            multiSelectionKeyCode={["Control", "Meta"]}
          >
            <Background gap={16} size={1} />
            <MiniMap pannable zoomable />
            <Controls showInteractive />
          </ReactFlow>
        </div>
        <aside className="visual-inspector-panel">
          {selectedNode ? (
            <NodeInspector
              node={selectedNode}
              onChange={updateSelected}
              onDuplicate={() => {
                snapshot();
                const copy = { ...selectedNode, id: `${selectedNode.data.nodeType}_${crypto.randomUUID().slice(0, 8)}`, position: { x: selectedNode.position.x + 32, y: selectedNode.position.y + 32 }, selected: false };
                setNodes((current) => [...current, copy]);
                setDirty(true);
              }}
              onDelete={() => changeNodes([{ id: selectedNode.id, type: "remove" }])}
            />
          ) : (
            <div className="inspector-empty"><Archive size={22} /><strong>Select a node</strong><p>Configure fields, bindings, behavior, and validation from this panel.</p></div>
          )}
          <details className="version-history">
            <summary><History size={15} /> Version history</summary>
            {(versions.data || []).map((version) => (
              <div key={version.revision} className="version-row">
                <span><strong>Revision {version.revision}</strong><small>{version.message || "Saved revision"}</small></span>
                {version.published ? <Check size={15} /> : <button title={`Restore revision ${version.revision}`} onClick={async () => {
                  const restored = await restoreArtifactVersion(artifact.id, version.revision);
                  queryClient.setQueryData<PlatformArtifact[]>(["artifacts", artifactType], (items = []) => items.map((item) => item.id === restored.id ? restored : item));
                  await queryClient.invalidateQueries({ queryKey: ["artifact-versions", artifact.id] });
                }}>Restore</button>}
              </div>
            ))}
          </details>
        </aside>
      </div>
    </section>
  );
}

function NodeInspector({ node, onChange, onDuplicate, onDelete }: { node: Node<ArtifactNodeData>; onChange: (data: ArtifactNodeData) => void; onDuplicate: () => void; onDelete: () => void }) {
  const fields = node.data.fields || [];
  function reorder(event: DragEndEvent) {
    if (!event.over || event.active.id === event.over.id) return;
    const from = fields.findIndex((field) => field.id === event.active.id);
    const to = fields.findIndex((field) => field.id === event.over?.id);
    onChange({ ...node.data, fields: arrayMove(fields, from, to) });
  }
  return (
    <div className="node-inspector-form">
      <div className="inspector-heading"><div><span className="eyebrow">{node.data.nodeType}</span><h2>Node settings</h2></div><div><button title="Duplicate node" onClick={onDuplicate}><Copy size={15} /></button><button title="Delete node" onClick={onDelete}><Trash2 size={15} /></button></div></div>
      <label>Name<input value={node.data.label} onChange={(event) => onChange({ ...node.data, label: event.target.value })} /></label>
      <label>Description<textarea rows={3} value={node.data.description || ""} onChange={(event) => onChange({ ...node.data, description: event.target.value })} /></label>
      <div className="field-list-heading"><strong>Configuration fields</strong><button onClick={() => onChange({ ...node.data, fields: [...fields, { id: crypto.randomUUID(), name: "field", value: "" }] })}><Plus size={14} /> Add</button></div>
      <DndContext collisionDetection={closestCenter} onDragEnd={reorder}>
        <SortableContext items={fields.map((field) => field.id)} strategy={verticalListSortingStrategy}>
          <div className="config-field-list">
            {fields.map((field) => <SortableField key={field.id} field={field} onChange={(next) => onChange({ ...node.data, fields: fields.map((item) => item.id === field.id ? next : item) })} onDelete={() => onChange({ ...node.data, fields: fields.filter((item) => item.id !== field.id) })} />)}
          </div>
        </SortableContext>
      </DndContext>
    </div>
  );
}

function SortableField({ field, onChange, onDelete }: { field: { id: string; name: string; value: string }; onChange: (field: { id: string; name: string; value: string }) => void; onDelete: () => void }) {
  const sortable = useSortable({ id: field.id });
  return (
    <div ref={sortable.setNodeRef} style={{ transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition }} className="config-field-row">
      <button className="drag-grip" aria-label={`Reorder ${field.name}`} {...sortable.attributes} {...sortable.listeners}>⋮⋮</button>
      <input aria-label="Field name" value={field.name} onChange={(event) => onChange({ ...field, name: event.target.value })} />
      <input aria-label="Field value" value={field.value} onChange={(event) => onChange({ ...field, value: event.target.value })} />
      <button aria-label={`Delete ${field.name}`} onClick={onDelete}><Trash2 size={14} /></button>
    </div>
  );
}
