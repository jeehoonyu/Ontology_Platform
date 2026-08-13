import { api } from "../api";
import type { PipelineOntologyContractState } from "../types";

export function getPipelineOntologyContracts(graphId: string): Promise<PipelineOntologyContractState> {
  return api<PipelineOntologyContractState>(
    `/ui-state/pipeline/${encodeURIComponent(graphId)}/ontology-contracts`
  );
}
