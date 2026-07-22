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
