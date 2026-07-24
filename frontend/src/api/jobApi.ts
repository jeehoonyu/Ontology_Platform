import { api, postJson } from "../api";
import type { JobSummary, JsonObject, PlatformJob } from "../types";

export function getJobSummary(): Promise<JobSummary> {
  return api<JobSummary>("/jobs/summary");
}

export function getJob(jobId: string): Promise<PlatformJob> {
  return api<PlatformJob>(`/jobs/${encodeURIComponent(jobId)}`);
}

export function cancelJob(jobId: string): Promise<PlatformJob> {
  return postJson<PlatformJob>(`/jobs/${encodeURIComponent(jobId)}/cancel`, {});
}

export function retryJob(jobId: string): Promise<PlatformJob> {
  return postJson<PlatformJob>(`/jobs/${encodeURIComponent(jobId)}/retry`, {});
}

export function enqueuePipelineJob(graphId: string, action: "preview" | "deliver", idempotencyKey: string): Promise<PlatformJob> {
  return postJson<PlatformJob>(`/pipeline-builder/graphs/${encodeURIComponent(graphId)}/${action}/async`, {
    idempotency_key: idempotencyKey
  });
}

export function runPipelineJob(jobId: string): Promise<{ job: PlatformJob | null; result: JsonObject | null }> {
  return postJson(`/pipeline-builder/workers/run-next`, {
    worker_id: "react-pipeline-worker",
    job_id: jobId,
    lease_seconds: 120
  });
}
