import { api } from "../api";
import type { JobSummary } from "../types";

export function getJobSummary(): Promise<JobSummary> {
  return api<JobSummary>("/jobs/summary");
}
