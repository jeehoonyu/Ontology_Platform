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
  AlignHorizontalSpaceAround,
  Check,
  Copy,
  Eye,
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
  applyArtifactCommands,
  applyCollaborativeCommands,
  artifactCollaborationStreamUrl,
  createArtifact,
  getArtifactCollaboration,
  getBuilderCatalog,
  heartbeatArtifactCollaboration,
  joinArtifactCollaboration,
  leaveArtifactCollaboration,
  listArtifacts,
  listArtifactVersions,
  publishArtifact,
  previewArtifact,
  restoreArtifactVersion,
  type ArtifactCollaborationEvent,
  type ArtifactCollaborationSession,
  type ArtifactLease,
  type ArtifactNodeData,
  type ArtifactPreview,
  type ArtifactState,
  type ArtifactType,
  type PlatformArtifact
} from "../api/artifactApi";
import { EmptyState, ErrorBanner, LoadingState, StatusBadge } from "../components/data/DataDisplay";
import { autoLayout, diffArtifactCommands, duplicateSelection, removeSelection, replaceStateCommand, selectedNodeIds } from "../lib/builderKernel";
import { AgentRuntimePanel } from "./AgentRuntimePanel";

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

function collaborationClientId(): string {
  const key = "ontology-platform-collaboration-client";
  const existing = window.localStorage.getItem(key);
  if (existing) return existing;
  const created = crypto.randomUUID();
  window.localStorage.setItem(key, created);
  return created;
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
  const [collaboration, setCollaboration] = useState<ArtifactCollaborationSession | null>(null);
  const [collaborationConflict, setCollaborationConflict] = useState("");
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [instance, setInstance] = useState<ReactFlowInstance<Node<ArtifactNodeData>, Edge> | null>(null);
  const [preview, setPreview] = useState<ArtifactPreview | null>(null);
  const [breakpoint, setBreakpoint] = useState<"desktop" | "tablet" | "mobile">("desktop");
  const undoStack = useRef<Array<{ nodes: Node<ArtifactNodeData>[]; edges: Edge[] }>>([]);
  const redoStack = useRef<Array<{ nodes: Node<ArtifactNodeData>[]; edges: Edge[] }>>([]);
  const hydratedArtifact = useRef("");
  const clipboard = useRef<{ nodes: Node<ArtifactNodeData>[]; edges: Edge[] } | null>(null);
  const dirtyRef = useRef(false);
  const selectionRef = useRef<string[]>([]);
  const catalog = useQuery({
    queryKey: ["builder-catalog", artifactType],
    queryFn: () => getBuilderCatalog(artifactType),
    enabled: ["pipeline", "ontology", "workshop", "aip_logic"].includes(artifactType),
    retry: false
  });
  const catalogLibrary = catalog.data?.nodes || LIBRARIES[artifactType] || [];
  const library = catalogLibrary.filter((item) => item.label.toLowerCase().includes(search.toLowerCase()));

  const versions = useQuery({
    queryKey: ["artifact-versions", artifact?.id],
    queryFn: () => listArtifactVersions(artifact!.id),
    enabled: Boolean(artifact)
  });

  const collaborators = useQuery({
    queryKey: ["artifact-collaboration", artifact?.id],
    queryFn: () => getArtifactCollaboration(artifact!.id),
    enabled: Boolean(artifact && collaboration),
    refetchInterval: 4_000
  });

  useEffect(() => {
    dirtyRef.current = dirty;
  }, [dirty]);

  useEffect(() => {
    selectionRef.current = selectedNodeIds(nodes);
  }, [nodes]);

  useEffect(() => {
    if (!artifact || !collaborators.data || collaborators.data.lock_version <= artifact.lock_version) return;
    if (dirtyRef.current) {
      setCollaborationConflict("A newer shared revision is available while you have local changes.");
    } else {
      queryClient.invalidateQueries({ queryKey: ["artifacts", artifactType] });
      queryClient.invalidateQueries({ queryKey: ["artifact-versions", artifact.id] });
    }
  }, [artifact, artifactType, collaborators.data?.lock_version, queryClient]);

  useEffect(() => {
    if (!artifact || hydratedArtifact.current === `${artifact.id}:${artifact.current_revision}`) return;
    if (dirtyRef.current && hydratedArtifact.current.startsWith(`${artifact.id}:`)) {
      setCollaborationConflict("A newer shared revision is available. Reload it or finish resolving your local changes before saving.");
      return;
    }
    setNodes(stateNodes(artifact));
    setEdges(stateEdges(artifact));
    setDirty(false);
    setSelectedNodeId("");
    setCollaborationConflict("");
    hydratedArtifact.current = `${artifact.id}:${artifact.current_revision}`;
  }, [artifact]);

  useEffect(() => {
    if (!artifact) return;
    let active = true;
    setCollaboration(null);
    setLease(null);
    joinArtifactCollaboration(artifact.id, collaborationClientId())
      .then((session) => {
        if (active) setCollaboration(session);
      })
      .catch(async (collaborationError) => {
        try {
          const fallbackLease = await acquireArtifactLease(artifact.id);
          if (active) {
            setLease(fallbackLease);
            setMessage("Live collaboration is unavailable. Editing is using a temporary exclusive lease.");
          }
        } catch {
          if (active) setMessage(collaborationError instanceof Error ? collaborationError.message : String(collaborationError));
        }
      });
    return () => {
      active = false;
    };
  }, [artifact?.id]);

  useEffect(() => {
    if (!artifact || !collaboration) return;
    const heartbeat = () => heartbeatArtifactCollaboration(
      artifact.id,
      collaboration.participant_token,
      selectionRef.current
    ).then(() => queryClient.invalidateQueries({ queryKey: ["artifact-collaboration", artifact.id] })).catch(() => undefined);
    heartbeat();
    const timer = window.setInterval(heartbeat, 20_000);
    return () => {
      window.clearInterval(timer);
      leaveArtifactCollaboration(artifact.id, collaboration.participant_token).catch(() => undefined);
    };
  }, [artifact?.id, collaboration?.participant_token, queryClient]);

  useEffect(() => {
    if (!artifact || !collaboration) return;
    const stream = new EventSource(artifactCollaborationStreamUrl(artifact.id, collaboration.event_cursor));
    const receive = (raw: Event) => {
      const event = JSON.parse((raw as MessageEvent<string>).data) as ArtifactCollaborationEvent;
      queryClient.invalidateQueries({ queryKey: ["artifact-collaboration", artifact.id] });
      if (event.participant_id === collaboration.participant.id) return;
      if (["artifact.commands", "artifact.revision", "artifact.published", "artifact.restored"].includes(event.event_type)) {
        if (dirtyRef.current) {
          setCollaborationConflict(`${event.actor} updated this artifact while you have local changes.`);
        } else {
          queryClient.invalidateQueries({ queryKey: ["artifacts", artifactType] });
          queryClient.invalidateQueries({ queryKey: ["artifact-versions", artifact.id] });
        }
      }
    };
    ["presence.joined", "presence.rejoined", "presence.updated", "presence.left", "artifact.commands", "artifact.revision", "artifact.published", "artifact.restored", "artifact.conflict"]
      .forEach((name) => stream.addEventListener(name, receive));
    stream.onerror = () => setMessage("Live updates disconnected. Reconnecting automatically...");
    return () => stream.close();
  }, [artifact?.id, artifactType, collaboration?.participant.id, collaboration?.event_cursor, queryClient]);

  const createMutation = useMutation({
    mutationFn: () => createArtifact(artifactType, `${title} draft`),
    onSuccess: async (created) => {
      setSelectedId(created.id);
      await queryClient.invalidateQueries({ queryKey: ["artifacts", artifactType] });
    }
  });

  const saveMutation = useMutation({
    mutationFn: async ({ reason }: { reason: string }) => {
      if (!artifact) throw new Error("Select an artifact before saving.");
      if (collaboration) {
        const commands = diffArtifactCommands(artifact.state, nodes, edges);
        if (!commands.length) return artifact;
        return applyCollaborativeCommands(artifact, collaboration.participant_token, commands, reason);
      }
      if (!lease) throw new Error("The editor is not connected. Wait for collaboration or an editing lease.");
      return applyArtifactCommands(artifact, [replaceStateCommand(nodes, edges, artifact.state)], lease.token, reason);
    },
    onSuccess: async (saved) => {
      setDirty(false);
      setMessage(`Saved revision ${saved.current_revision}`);
      setCollaborationConflict("");
      hydratedArtifact.current = `${saved.id}:${saved.current_revision}`;
      queryClient.setQueryData<PlatformArtifact[]>(["artifacts", artifactType], (current = []) => current.map((item) => item.id === saved.id ? saved : item));
      await queryClient.invalidateQueries({ queryKey: ["artifact-versions", saved.id] });
    },
    onError: (error) => {
      const detail = error instanceof Error ? error.message : String(error);
      if (collaboration) setCollaborationConflict(`Your changes overlap a newer shared edit. ${detail}`);
      setMessage(detail);
    }
  });

  const previewMutation = useMutation({
    mutationFn: () => {
      if (!artifact) throw new Error("Select an artifact before previewing.");
      return previewArtifact(artifact.id);
    },
    onSuccess: (result) => {
      setPreview(result);
      setMessage(`Preview completed in ${result.metrics.duration_ms} ms`);
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : String(error))
  });

  useEffect(() => {
    if (!dirty || !artifact || (!collaboration && !lease) || collaborationConflict || saveMutation.isPending) return;
    const timer = window.setTimeout(() => saveMutation.mutate({ reason: "Autosaved visual edit" }), 1200);
    return () => window.clearTimeout(timer);
  }, [dirty, nodes, edges, artifact?.id, artifact?.lock_version, collaboration?.participant_token, lease?.token, collaborationConflict]);

  function snapshot() {
    undoStack.current.push({ nodes: structuredClone(nodes), edges: structuredClone(edges) });
    if (undoStack.current.length > 50) undoStack.current.shift();
    redoStack.current = [];
  }

  function changeNodes(changes: NodeChange<Node<ArtifactNodeData>>[]) {
    const persistent = changes.some((change) => change.type === "add" || change.type === "remove" || change.type === "position");
    if (persistent) snapshot();
    setNodes((current) => applyNodeChanges(changes, current));
    if (persistent) setDirty(true);
  }

  function changeEdges(changes: EdgeChange<Edge>[]) {
    const persistent = changes.some((change) => change.type === "add" || change.type === "remove" || change.type === "replace");
    if (persistent) snapshot();
    setEdges((current) => applyEdgeChanges(changes, current));
    if (persistent) setDirty(true);
  }

  function connect(connection: Connection) {
    snapshot();
    setEdges((current) => addEdge({ ...connection, id: crypto.randomUUID() }, current));
    setDirty(true);
  }

  function addNode(nodeType: string, position?: { x: number; y: number }) {
    const item = catalogLibrary.find((entry) => entry.type === nodeType);
    if (!item) return;
    snapshot();
    const id = `${nodeType}_${crypto.randomUUID().slice(0, 8)}`;
    type FieldDefinition = { label?: string; type?: string; required?: boolean; options?: string[]; default?: unknown };
    const schema = ("configuration_schema" in item ? item.configuration_schema : undefined) as { properties?: Record<string, FieldDefinition> } | undefined;
    const properties = schema?.properties || {};
    setNodes((current) => [...current, {
      id,
      position: position || { x: 120 + current.length * 28, y: 100 + current.length * 28 },
      data: {
        label: item.label,
        description: item.description,
        nodeType,
        configurationSchemaVersion: 1,
        fields: Object.entries(properties).map(([name, definition]) => ({
          id: crypto.randomUUID(), name, label: definition.label || name.replace(/_/g, " "),
          value: definition.default == null ? "" : String(definition.default), type: definition.type || "string",
          required: Boolean(definition.required), options: definition.options
        }))
      },
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

  function duplicateNodes(ids = selectedNodeIds(nodes).length ? selectedNodeIds(nodes) : selectedNodeId ? [selectedNodeId] : []) {
    if (!ids.length) return;
    snapshot();
    const next = duplicateSelection({ nodes, edges }, ids);
    setNodes(next.nodes);
    setEdges(next.edges);
    setSelectedNodeId(next.nodes.find((node) => node.selected)?.id || "");
    setDirty(true);
  }

  function deleteSelection() {
    const nodeIds = selectedNodeIds(nodes).length ? selectedNodeIds(nodes) : selectedNodeId ? [selectedNodeId] : [];
    const edgeIds = edges.filter((edge) => edge.selected).map((edge) => edge.id);
    if (!nodeIds.length && !edgeIds.length) return;
    snapshot();
    const next = removeSelection({ nodes, edges }, nodeIds, edgeIds);
    setNodes(next.nodes);
    setEdges(next.edges);
    setSelectedNodeId("");
    setDirty(true);
  }

  function copySelection() {
    const ids = new Set(selectedNodeIds(nodes).length ? selectedNodeIds(nodes) : selectedNodeId ? [selectedNodeId] : []);
    if (!ids.size) return;
    clipboard.current = {
      nodes: structuredClone(nodes.filter((node) => ids.has(node.id))),
      edges: structuredClone(edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)))
    };
    setMessage(`${ids.size} node${ids.size === 1 ? "" : "s"} copied`);
  }

  function pasteSelection() {
    if (!clipboard.current) return;
    const source = clipboard.current;
    const idMap = new Map<string, string>();
    const pastedNodes = source.nodes.map((node) => {
      const id = `${node.data.nodeType}_${crypto.randomUUID().slice(0, 8)}`;
      idMap.set(node.id, id);
      return { ...structuredClone(node), id, selected: true, position: { x: node.position.x + 48, y: node.position.y + 48 } };
    });
    const pastedEdges = source.edges.map((edge) => ({
      ...structuredClone(edge), id: `edge_${crypto.randomUUID().slice(0, 10)}`,
      source: idMap.get(edge.source)!, target: idMap.get(edge.target)!, selected: false
    }));
    setNodes((current) => [...current.map((node) => ({ ...node, selected: false })), ...pastedNodes]);
    setEdges((current) => [...current, ...pastedEdges]);
    setSelectedNodeId(pastedNodes[0]?.id || "");
    setDirty(true);
  }

  function layoutNodes() {
    snapshot();
    setNodes((current) => autoLayout(current));
    setDirty(true);
    window.setTimeout(() => instance?.fitView({ padding: 0.2, duration: 300 }), 0);
  }

  useEffect(() => {
    function handleKeyboard(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      const modifier = event.ctrlKey || event.metaKey;
      if (modifier && event.key.toLowerCase() === "z") {
        event.preventDefault();
        event.shiftKey ? redo() : undo();
      } else if (modifier && event.key.toLowerCase() === "y") {
        event.preventDefault();
        redo();
      } else if (modifier && event.key.toLowerCase() === "c") {
        event.preventDefault();
        copySelection();
      } else if (modifier && event.key.toLowerCase() === "v") {
        event.preventDefault();
        snapshot();
        pasteSelection();
      } else if (modifier && event.key.toLowerCase() === "d") {
        event.preventDefault();
        duplicateNodes();
      } else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        deleteSelection();
      }
    }
    window.addEventListener("keydown", handleKeyboard);
    return () => window.removeEventListener("keydown", handleKeyboard);
  }, [nodes, edges, selectedNodeId]);

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
          <div className="collaboration-presence" aria-label={`${collaborators.data?.participants.length || 0} active editors`}>
            {(collaborators.data?.participants || []).slice(0, 4).map((participant) => (
              <span
                className="collaboration-avatar"
                style={{ backgroundColor: participant.color }}
                title={`${participant.display_name}${participant.id === collaboration?.participant.id ? " (you)" : ""}`}
                key={participant.id}
              >{participant.display_name.slice(0, 1).toUpperCase()}</span>
            ))}
            <small>{collaboration ? `${collaborators.data?.participants.length || 1} editing` : lease ? "Exclusive edit" : "Connecting"}</small>
          </div>
          <StatusBadge value={dirty ? "UNSAVED" : saveMutation.isPending ? "SAVING" : artifact.status} />
          <button title="Undo" aria-label="Undo" onClick={undo} disabled={!undoStack.current.length}><Undo2 size={16} /></button>
          <button title="Redo" aria-label="Redo" onClick={redo} disabled={!redoStack.current.length}><Redo2 size={16} /></button>
          <button title="Auto-layout nodes" onClick={layoutNodes}><AlignHorizontalSpaceAround size={16} /> Layout</button>
          {artifactType === "workshop" ? <div className="builder-breakpoint-control" aria-label="Workshop breakpoint">{(["desktop", "tablet", "mobile"] as const).map((item) => <button type="button" className={breakpoint === item ? "active" : ""} onClick={() => setBreakpoint(item)} key={item}>{item}</button>)}</div> : null}
          <button onClick={() => previewMutation.mutate()} disabled={previewMutation.isPending}><Eye size={16} /> {previewMutation.isPending ? "Running" : "Preview"}</button>
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
      {collaborationConflict ? (
        <div className="collaboration-conflict" role="alert">
          <div><strong>Shared edit needs review</strong><span>{collaborationConflict}</span></div>
          <button onClick={async () => {
            setDirty(false);
            dirtyRef.current = false;
            setCollaborationConflict("");
            hydratedArtifact.current = "";
            await queryClient.invalidateQueries({ queryKey: ["artifacts", artifactType] });
          }}>Reload shared revision</button>
        </div>
      ) : null}
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
                <Plus size={14} /><span><strong>{item.label}</strong><small>{"category" in item ? `${item.category} · ` : ""}{item.description}</small></span>
              </button>
            ))}
          </div>
        </aside>
        <div className="visual-builder-center">
          <div className={`visual-flow-canvas visual-breakpoint-${breakpoint}`} onDrop={drop} onDragOver={(event) => event.preventDefault()}>
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
              deleteKeyCode={null}
              multiSelectionKeyCode={["Control", "Meta"]}
              selectionOnDrag
              panOnDrag={[1, 2]}
            >
              <Background gap={16} size={1} />
              <MiniMap pannable zoomable />
              <Controls showInteractive />
            </ReactFlow>
          </div>
          <section className="builder-execution-drawer" aria-label="Builder preview and validation">
            <div className="builder-drawer-tabs"><strong>Preview</strong><span>Validation</span><span>Evidence</span></div>
            <div className="builder-drawer-content">
              {preview ? (
                <>
                  <div className="preview-metrics">
                    <span><strong>{preview.metrics.node_count}</strong> nodes</span>
                    <span><strong>{preview.metrics.edge_count}</strong> edges</span>
                    <span><strong>{preview.metrics.duration_ms} ms</strong> duration</span>
                    <StatusBadge value={preview.status} />
                  </div>
                  <div className="preview-row-list">{preview.sample_output.slice(0, 6).map((row) => <span key={row.node_id}><strong>{row.label}</strong><small>{row.node_type}</small><StatusBadge value={row.status} /></span>)}</div>
                </>
              ) : (
                <p>Select Preview to validate the current revision and inspect deterministic execution evidence.</p>
              )}
            </div>
            {artifactType === "aip_logic" ? <AgentRuntimePanel /> : null}
          </section>
        </div>
        <aside className="visual-inspector-panel">
          {selectedNode ? (
            <NodeInspector
              node={selectedNode}
              onChange={updateSelected}
              onDuplicate={() => duplicateNodes([selectedNode.id])}
              onDelete={deleteSelection}
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
          <details className="version-history" open={Boolean(artifact.validation_targets?.length)}>
            <summary>Validation targets <StatusBadge value={artifact.validation?.status || "UNKNOWN"} /></summary>
            {(artifact.validation_targets || []).length ? artifact.validation_targets.map((target, index) => (
              <div className="version-row" key={`${target.path}-${index}`}><span><strong>{target.severity}</strong><small>{target.message}</small></span></div>
            )) : <div className="version-row"><span><strong>Ready</strong><small>No targeted validation issues.</small></span></div>}
          </details>
          <details className="version-history">
            <summary>Evidence</summary>
            {(artifact.evidence_links || []).map((link) => <a className="builder-evidence-link" href={link.href} key={link.href}>{link.label}</a>)}
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
      <div className="field-list-heading"><strong>Configuration fields</strong><button onClick={() => onChange({ ...node.data, fields: [...fields, { id: crypto.randomUUID(), name: "field", label: "Custom field", value: "", type: "string" }] })}><Plus size={14} /> Add</button></div>
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

type InspectorField = NonNullable<ArtifactNodeData["fields"]>[number];

function SortableField({ field, onChange, onDelete }: { field: InspectorField; onChange: (field: InspectorField) => void; onDelete: () => void }) {
  const sortable = useSortable({ id: field.id });
  return (
    <div ref={sortable.setNodeRef} style={{ transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition }} className="config-field-row">
      <button className="drag-grip" aria-label={`Reorder ${field.name}`} {...sortable.attributes} {...sortable.listeners}>⋮⋮</button>
      <span className="config-field-label"><strong>{field.label || field.name}</strong><small>{field.required ? "Required" : field.type || "string"}</small></span>
      {field.type === "select" ? (
        <select aria-label={field.label || field.name} value={field.value} onChange={(event) => onChange({ ...field, value: event.target.value })}><option value="">Choose...</option>{(field.options || []).map((option) => <option value={option} key={option}>{option.replace(/_/g, " ")}</option>)}</select>
      ) : field.type === "boolean" ? (
        <label className="config-boolean"><input type="checkbox" checked={field.value === "true"} onChange={(event) => onChange({ ...field, value: String(event.target.checked) })} /> Enabled</label>
      ) : field.type === "textarea" ? (
        <textarea aria-label={field.label || field.name} rows={3} value={field.value} onChange={(event) => onChange({ ...field, value: event.target.value })} />
      ) : (
        <input aria-label={field.label || field.name} type={["integer", "number"].includes(field.type || "") ? "number" : "text"} placeholder={field.type === "field_list" ? "value_a, value_b" : undefined} value={field.value} onChange={(event) => onChange({ ...field, value: event.target.value })} />
      )}
      <button aria-label={`Delete ${field.name}`} onClick={onDelete}><Trash2 size={14} /></button>
    </div>
  );
}
