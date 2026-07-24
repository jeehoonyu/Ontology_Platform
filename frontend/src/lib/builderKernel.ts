import type { Edge, Node } from "@xyflow/react";
import type { ArtifactNodeData, ArtifactState, BuilderCommand } from "../api/artifactApi";

export interface BuilderSnapshot {
  nodes: Node<ArtifactNodeData>[];
  edges: Edge[];
}

export function selectedNodeIds(nodes: Node<ArtifactNodeData>[]): string[] {
  return nodes.filter((node) => node.selected).map((node) => node.id);
}

export function duplicateSelection(snapshot: BuilderSnapshot, ids: string[], offset = 32): BuilderSnapshot {
  const selected = new Set(ids);
  const idMap = new Map<string, string>();
  const copies = snapshot.nodes.filter((node) => selected.has(node.id)).map((node) => {
    const id = `${node.data.nodeType}_${crypto.randomUUID().slice(0, 8)}`;
    idMap.set(node.id, id);
    return { ...structuredClone(node), id, selected: true, position: { x: node.position.x + offset, y: node.position.y + offset } };
  });
  const copiedEdges = snapshot.edges.filter((edge) => selected.has(edge.source) && selected.has(edge.target)).map((edge) => ({
    ...structuredClone(edge), id: `edge_${crypto.randomUUID().slice(0, 10)}`, source: idMap.get(edge.source)!, target: idMap.get(edge.target)!
  }));
  return {
    nodes: [...snapshot.nodes.map((node) => ({ ...node, selected: false })), ...copies],
    edges: [...snapshot.edges, ...copiedEdges]
  };
}

export function removeSelection(snapshot: BuilderSnapshot, nodeIds: string[], edgeIds: string[] = []): BuilderSnapshot {
  const removedNodes = new Set(nodeIds);
  const removedEdges = new Set(edgeIds);
  return {
    nodes: snapshot.nodes.filter((node) => !removedNodes.has(node.id)),
    edges: snapshot.edges.filter((edge) => !removedEdges.has(edge.id) && !removedNodes.has(edge.source) && !removedNodes.has(edge.target))
  };
}

export function autoLayout(nodes: Node<ArtifactNodeData>[], columns = 4): Node<ArtifactNodeData>[] {
  return nodes.map((node, index) => ({
    ...node,
    position: { x: 80 + (index % columns) * 280, y: 80 + Math.floor(index / columns) * 160 }
  }));
}

export function replaceStateCommand(nodes: Node<ArtifactNodeData>[], edges: Edge[], base: ArtifactState): BuilderCommand {
  const state: ArtifactState = {
    ...base,
    nodes: nodes.map(({ id, type, position, data }) => ({ id, type, position, data })),
    edges: edges.map(({ id, source, target, sourceHandle, targetHandle }) => ({ id, source, target, sourceHandle, targetHandle }))
  };
  return {
    command: "replace_state",
    payload: { state, layout: Object.fromEntries(nodes.map((node) => [node.id, node.position])) }
  };
}

function persistedNode(node: Node<ArtifactNodeData>) {
  return { id: node.id, type: node.type, position: node.position, data: node.data };
}

function persistedEdge(edge: Edge) {
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle,
    targetHandle: edge.targetHandle
  };
}

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function diffArtifactCommands(
  base: ArtifactState,
  nodes: Node<ArtifactNodeData>[],
  edges: Edge[]
): BuilderCommand[] {
  const commands: BuilderCommand[] = [];
  const baseNodes = new Map((base.nodes || []).map((node) => [node.id, node]));
  const nextNodes = new Map(nodes.map((node) => [node.id, node]));
  const removedNodeIds = [...baseNodes.keys()].filter((id) => !nextNodes.has(id));
  if (removedNodeIds.length) commands.push({ command: "remove_nodes", payload: { node_ids: removedNodeIds } });

  const positions: Record<string, { x: number; y: number }> = {};
  for (const node of nodes) {
    const previous = baseNodes.get(node.id);
    if (!previous) {
      commands.push({ command: "add_node", payload: { node: persistedNode(node) } });
      continue;
    }
    if (!sameValue(previous.data, node.data) || previous.type !== node.type) {
      commands.push({
        command: "update_node",
        payload: { node_id: node.id, changes: { type: node.type, data: node.data } }
      });
    }
    if (!sameValue(previous.position, node.position)) positions[node.id] = node.position;
  }
  if (Object.keys(positions).length) commands.push({ command: "move_nodes", payload: { positions } });

  const baseEdges = new Map((base.edges || []).map((edge) => [edge.id, edge]));
  const nextEdges = new Map(edges.map((edge) => [edge.id, edge]));
  const removedEdgeIds = [...baseEdges.keys()].filter((id) => !nextEdges.has(id));
  if (removedEdgeIds.length) commands.push({ command: "remove_edges", payload: { edge_ids: removedEdgeIds } });
  for (const edge of edges) {
    const previous = baseEdges.get(edge.id);
    if (!previous) {
      commands.push({ command: "add_edge", payload: { edge: persistedEdge(edge) } });
    } else if (!sameValue(previous, persistedEdge(edge))) {
      commands.push({ command: "remove_edges", payload: { edge_ids: [edge.id] } });
      commands.push({ command: "add_edge", payload: { edge: persistedEdge(edge) } });
    }
  }
  return commands;
}
