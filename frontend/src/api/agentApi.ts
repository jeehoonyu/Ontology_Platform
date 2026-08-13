import { api, postJson } from "../api";
import type { AgentDefinition, AgentRunResult, PlatformJob } from "../types";
import type { JsonObject } from "../types";

export function listAgents(): Promise<AgentDefinition[]> {
  return api<AgentDefinition[]>("/agents");
}

export function enqueueAgentInvocation(
  agentId: string,
  prompt: string,
  parameters: JsonObject,
  idempotencyKey: string
): Promise<PlatformJob> {
  return postJson<PlatformJob>(`/aip/agents/${encodeURIComponent(agentId)}/invoke/async`, {
    prompt,
    parameters,
    idempotency_key: idempotencyKey
  });
}

export function enqueueAgentTaskGraph(
  agentId: string,
  prompt: string,
  parameters: JsonObject,
  idempotencyKey: string
): Promise<PlatformJob> {
  return postJson<PlatformJob>(`/api/v1/agents/${encodeURIComponent(agentId)}/task-graphs`, {
    prompt,
    parameters,
    idempotency_key: idempotencyKey,
    max_parallel_tools: 20
  });
}

export function cancelAgentTask(taskId: string): Promise<PlatformJob> {
  return postJson<PlatformJob>(`/api/v1/agents/tasks/${encodeURIComponent(taskId)}/cancel`, {});
}

export function retryAgentTask(taskId: string): Promise<PlatformJob> {
  return postJson<PlatformJob>(`/api/v1/agents/tasks/${encodeURIComponent(taskId)}/retry`, {});
}

export function runAgentJob(jobId: string): Promise<{ job: PlatformJob | null; result: AgentRunResult | null }> {
  return postJson("/aip/agents/workers/run-next", {
    worker_id: "react-aip-agent-worker",
    job_id: jobId,
    lease_seconds: 120
  });
}

export function listAgentRuns(agentId: string): Promise<AgentRunResult[]> {
  return api<AgentRunResult[]>(`/aip/agents/${encodeURIComponent(agentId)}/runs`);
}
