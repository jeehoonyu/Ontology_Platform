import { api, postJson } from "../api";
import type {
  JsonObject,
  NodePreview,
  NodeSuggestions,
  OntologyManagerState,
  OntologySectionState,
  OntologyUiState,
  OntologyWalkthrough,
  PipelineCanvasState,
  PipelineNodeDetails,
  PipelineOutputsState,
  PipelineUiState,
  WorkflowState
} from "../types";

export function getWorkflowState(): Promise<WorkflowState> {
  return api<WorkflowState>("/scenarios/asset-reliability/workflow-state");
}

export function getPipelineState(): Promise<PipelineUiState> {
  return api<PipelineUiState>("/ui-state/pipeline");
}

export function getPipelineCanvas(graphId: string, selectedNodeId?: string): Promise<PipelineCanvasState> {
  const suffix = selectedNodeId ? `?selected_node_id=${encodeURIComponent(selectedNodeId)}` : "";
  return api<PipelineCanvasState>(`/ui-state/pipeline/${encodeURIComponent(graphId)}/canvas${suffix}`);
}

export function insertPipelineNode(graphId: string, nodeId: string, nodeType: string): Promise<PipelineCanvasState> {
  return postJson<PipelineCanvasState>(
    `/pipeline-builder/graphs/${encodeURIComponent(graphId)}/nodes/${encodeURIComponent(nodeId)}/insert-after`,
    { node_type: nodeType }
  );
}

export function savePipelineLayout(graphId: string, positions: Record<string, { x: number; y: number }>): Promise<PipelineCanvasState> {
  return api<PipelineCanvasState>(`/pipeline-builder/graphs/${encodeURIComponent(graphId)}/layout`, {
    method: "PATCH",
    body: JSON.stringify({ positions })
  });
}

export function previewPipelineNode(graphId: string, nodeId: string): Promise<NodePreview> {
  return postJson<NodePreview>(
    `/pipeline-builder/graphs/${encodeURIComponent(graphId)}/nodes/${encodeURIComponent(nodeId)}/preview`,
    { limit: 50 }
  );
}

export function suggestPipelineNode(graphId: string, nodeId: string): Promise<NodeSuggestions> {
  return postJson<NodeSuggestions>(
    `/pipeline-builder/graphs/${encodeURIComponent(graphId)}/nodes/${encodeURIComponent(nodeId)}/suggestions`,
    {}
  );
}

export function getPipelineNodeDetails(graphId: string, nodeId: string): Promise<PipelineNodeDetails> {
  return api<PipelineNodeDetails>(
    `/ui-state/pipeline/${encodeURIComponent(graphId)}/nodes/${encodeURIComponent(nodeId)}/details`
  );
}

export function getPipelineOutputs(graphId: string): Promise<PipelineOutputsState> {
  return api<PipelineOutputsState>(`/ui-state/pipeline/${encodeURIComponent(graphId)}/outputs`);
}

export function getOntologyState(): Promise<OntologyUiState> {
  return api<OntologyUiState>("/ui-state/ontology");
}

export function getOntologyObjectType(objectTypeId: string): Promise<OntologyManagerState> {
  return api<OntologyManagerState>(`/ui-state/ontology/object-types/${encodeURIComponent(objectTypeId)}`);
}

export function getOntologyWalkthrough(objectTypeId: string): Promise<OntologyWalkthrough> {
  return api<OntologyWalkthrough>(`/ui-state/ontology/object-types/${encodeURIComponent(objectTypeId)}/walkthrough`);
}

export function getOntologySection(objectTypeId: string, sectionId: string): Promise<OntologySectionState> {
  return api<OntologySectionState>(
    `/ui-state/ontology/object-types/${encodeURIComponent(objectTypeId)}/sections/${encodeURIComponent(sectionId)}`
  );
}

export function updateOntologyMetadata(objectTypeId: string, patch: JsonObject): Promise<OntologyManagerState> {
  return api<OntologyManagerState>(`/ontology/object-types/${encodeURIComponent(objectTypeId)}/metadata`, {
    method: "PATCH",
    body: JSON.stringify(patch)
  });
}

export function indexObjectType(objectTypeId: string): Promise<OntologyManagerState> {
  return postJson<OntologyManagerState>(`/ontology/object-types/${encodeURIComponent(objectTypeId)}/index`, {
    actor: "react"
  });
}
