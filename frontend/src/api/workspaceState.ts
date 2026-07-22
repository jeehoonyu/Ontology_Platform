import { api, postJson } from "../api";
import type {
  CommandCenterUiState,
  ImportsUiState,
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
  ProjectReadiness,
  ValidationUiState,
  WorkflowState
} from "../types";

export function getWorkflowState(): Promise<WorkflowState> {
  return api<WorkflowState>("/scenarios/asset-reliability/workflow-state");
}

export function getCommandCenterState(): Promise<CommandCenterUiState> {
  return api<CommandCenterUiState>("/ui-state/command-center");
}

export function bootstrapProjectDemo(): Promise<JsonObject> {
  return postJson<JsonObject>("/project/demo/bootstrap", { actor: "react", run_pipelines: true, run_checks: true });
}

export function resetProjectDemo(): Promise<JsonObject> {
  return postJson<JsonObject>("/project/demo/reset", { actor: "react", run_pipelines: true, run_checks: true });
}

export function getImportsState(): Promise<ImportsUiState> {
  return api<ImportsUiState>("/ui-state/imports");
}

export function getValidationState(): Promise<ValidationUiState> {
  return api<ValidationUiState>("/ui-state/validation");
}

export function getProjectReadiness(): Promise<ProjectReadiness> {
  return api<ProjectReadiness>("/project/readiness");
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

export function createPipelineNode(
  graphId: string,
  nodeType: string,
  position: { x: number; y: number },
  connectFromNodeId?: string
): Promise<PipelineCanvasState> {
  return postJson<PipelineCanvasState>(
    `/pipeline-builder/graphs/${encodeURIComponent(graphId)}/nodes`,
    {
      node_type: nodeType,
      position,
      connect_from_node_id: connectFromNodeId,
      actor: "react"
    }
  );
}

export function deletePipelineNode(graphId: string, nodeId: string): Promise<PipelineCanvasState> {
  return api<PipelineCanvasState>(
    `/pipeline-builder/graphs/${encodeURIComponent(graphId)}/nodes/${encodeURIComponent(nodeId)}`,
    { method: "DELETE" }
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

export function updatePipelineNode(graphId: string, nodeId: string, label: string, config: JsonObject): Promise<PipelineNodeDetails> {
  return api<PipelineNodeDetails>(
    `/pipeline-builder/graphs/${encodeURIComponent(graphId)}/nodes/${encodeURIComponent(nodeId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ label, config, actor: "react" })
    }
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

export function addOntologyProperty(objectTypeId: string, payload: JsonObject): Promise<OntologyManagerState> {
  return postJson<OntologyManagerState>(
    `/ontology/object-types/${encodeURIComponent(objectTypeId)}/properties`,
    { ...payload, actor: "react" }
  );
}

export function updateOntologyProperty(objectTypeId: string, propertyName: string, payload: JsonObject): Promise<OntologyManagerState> {
  return api<OntologyManagerState>(
    `/ontology/object-types/${encodeURIComponent(objectTypeId)}/properties/${encodeURIComponent(propertyName)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ ...payload, actor: "react" })
    }
  );
}

export function archiveOntologyProperty(objectTypeId: string, propertyName: string): Promise<OntologyManagerState> {
  return api<OntologyManagerState>(
    `/ontology/object-types/${encodeURIComponent(objectTypeId)}/properties/${encodeURIComponent(propertyName)}`,
    { method: "DELETE" }
  );
}

export function reorderOntologyProperties(objectTypeId: string, order: string[]): Promise<OntologyManagerState> {
  return api<OntologyManagerState>(
    `/ontology/object-types/${encodeURIComponent(objectTypeId)}/properties/order`,
    {
      method: "PATCH",
      body: JSON.stringify({ order, actor: "react" })
    }
  );
}

export function indexObjectType(objectTypeId: string): Promise<OntologyManagerState> {
  return postJson<OntologyManagerState>(`/ontology/object-types/${encodeURIComponent(objectTypeId)}/index`, {
    actor: "react"
  });
}
