import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Ban, Bot, Play, Plus, RotateCcw, Trash2 } from "lucide-react";
import {
  cancelAgentTask,
  enqueueAgentInvocation,
  enqueueAgentTaskGraph,
  listAgents,
  retryAgentTask,
  runAgentJob
} from "../api/agentApi";
import { getJob } from "../api/jobApi";
import { DataTable, ErrorBanner, StatusBadge } from "../components/data/DataDisplay";
import type { AgentRunResult, PlatformJob } from "../types";

export interface ParameterRow {
  id: string;
  name: string;
  value: string;
}

/**
 * What a person has chosen and typed here and not yet run. In AIP Logic this panel
 * sits in the Run results pane, and a pane moved to another slot is a new parent:
 * React remounts what it holds, and the agent, the execution mode, the instruction
 * and every parameter went back to their defaults. The builder holds it and hands
 * it back. The Decision workspace renders the panel in no pane and passes nothing,
 * so the panel keeps its own there. V12 of GOAL_MOVEMENT_2026-09-12.
 */
export interface AgentDraft {
  agentId: string;
  prompt: string;
  parameters: ParameterRow[];
  executionMode: "graph" | "single";
}

export const NEW_AGENT_DRAFT: AgentDraft = {
  agentId: "",
  prompt: "Inspect current operational risk and propose the safest next action.",
  parameters: [],
  executionMode: "graph"
};

function resultFromJob(job: PlatformJob | null): AgentRunResult | null {
  if (!job?.result || typeof job.result !== "object" || !("run_id" in job.result)) return null;
  return job.result as unknown as AgentRunResult;
}

/**
 * An agent run: its job, the task graph's stages, the result, and whether it is still
 * running. The panel used to keep these for itself, so a Run results pane moved to
 * another slot remounted them empty: a finished run's answer, citations and proposals
 * were gone, and a run in flight finished into a panel that no longer existed and was
 * never shown. The builder holds the run with this hook and hands it in, as it does
 * the draft; the Decision workspace passes nothing, and the panel runs its own.
 * V12 of GOAL_MOVEMENT_2026-09-12 recorded the draft; this is the run.
 */
export interface AgentRun {
  job: PlatformJob | null;
  graphStages: PlatformJob[];
  result: AgentRunResult | null;
  busy: boolean;
  error: string;
  invoke: (agentId: string, draft: AgentDraft) => Promise<void>;
  cancel: () => Promise<void>;
  retry: () => Promise<void>;
}

export function useAgentRun(): AgentRun {
  const [job, setJob] = useState<PlatformJob | null>(null);
  const [graphStages, setGraphStages] = useState<PlatformJob[]>([]);
  const [result, setResult] = useState<AgentRunResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!job || !["BLOCKED", "QUEUED", "RUNNING"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const current = await getJob(job.id);
        setJob(current);
        if (current.agent_task_graph) {
          const ids = [current.agent_task_graph.context_job_id, ...current.agent_task_graph.tool_job_ids];
          setGraphStages(await Promise.all(ids.map(getJob)));
        }
        const completed = resultFromJob(current);
        if (completed) setResult(completed);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status]);

  async function executeGraph(coordinator: PlatformJob) {
    const graph = coordinator.agent_task_graph;
    if (!graph) {
      const execution = await runAgentJob(coordinator.id);
      return execution;
    }
    const stageIds = [graph.context_job_id, ...graph.tool_job_ids];
    for (const stageId of stageIds) {
      const stage = await getJob(stageId);
      if (["QUEUED", "BLOCKED"].includes(stage.status)) {
        if (stage.status === "BLOCKED") continue;
        const executed = await runAgentJob(stageId);
        if (!executed.job || executed.job.status !== "SUCCEEDED") {
          setGraphStages(await Promise.all(stageIds.map(getJob)));
          return { job: await getJob(coordinator.id), result: null };
        }
      }
      setGraphStages(await Promise.all(stageIds.map(getJob)));
    }
    const ready = await getJob(coordinator.id);
    setJob(ready);
    return runAgentJob(coordinator.id);
  }

  async function invoke(agentId: string, { prompt, parameters, executionMode }: AgentDraft) {
    if (!agentId || !prompt.trim()) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const parameterValues = Object.fromEntries(parameters.filter((row) => row.name.trim()).map((row) => [row.name.trim(), row.value]));
      const queued = executionMode === "graph"
        ? await enqueueAgentTaskGraph(agentId, prompt.trim(), parameterValues, crypto.randomUUID())
        : await enqueueAgentInvocation(agentId, prompt.trim(), parameterValues, crypto.randomUUID());
      setJob(queued);
      setGraphStages([]);
      const execution = await executeGraph(queued);
      if (execution.job) {
        const detailed = await getJob(execution.job.id);
        setJob(detailed);
        setResult(execution.result || resultFromJob(detailed));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!job) return;
    try {
      setJob(await cancelAgentTask(job.id));
      if (job.agent_task_graph) {
        const ids = [job.agent_task_graph.context_job_id, ...job.agent_task_graph.tool_job_ids];
        setGraphStages(await Promise.all(ids.map(getJob)));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function retry() {
    if (!job) return;
    setBusy(true);
    try {
      const queued = await retryAgentTask(job.id);
      setJob(queued);
      const execution = await executeGraph(queued);
      if (execution.job) {
        const detailed = await getJob(execution.job.id);
        setJob(detailed);
        setResult(execution.result || resultFromJob(detailed));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  return { job, graphStages, result, busy, error, invoke, cancel, retry };
}

export function AgentRuntimePanel({ draft: held, onDraft, run: heldRun }: {
  /** Held by a caller whose pane can move, so a remount reads it back. */
  draft?: AgentDraft;
  onDraft?: (update: (current: AgentDraft) => AgentDraft) => void;
  /** The same, for the run: `useAgentRun` in the caller. */
  run?: AgentRun;
}) {
  const agents = useQuery({ queryKey: ["aip-agents"], queryFn: listAgents });
  const [own, setOwn] = useState<AgentDraft>(NEW_AGENT_DRAFT);
  const draft = held ?? own;
  const setDraft: (update: (current: AgentDraft) => AgentDraft) => void = onDraft ?? setOwn;
  const { agentId, prompt, parameters, executionMode } = draft;
  const setAgentId = (value: string) => setDraft((current) => ({ ...current, agentId: value }));
  const setPrompt = (value: string) => setDraft((current) => ({ ...current, prompt: value }));
  const setParameters = (update: (rows: ParameterRow[]) => ParameterRow[]) =>
    setDraft((current) => ({ ...current, parameters: update(current.parameters) }));
  const setExecutionMode = (value: "graph" | "single") => setDraft((current) => ({ ...current, executionMode: value }));
  const ownRun = useAgentRun();
  const { job, graphStages, result, busy, error, invoke, cancel, retry } = heldRun ?? ownRun;
  const selectedAgentId = agentId || agents.data?.[0]?.id || "";
  const policy = result?.policy_summary?.decision || (job?.status === "FAILED" ? "FAILED" : "NOT_RUN");
  const events = useMemo(() => job?.events || [], [job?.events]);

  return (
    <section className="agent-runtime-panel" aria-label="Durable agent runtime">
      <header>
        <div><Bot size={17} /><span><strong>Agent runtime</strong><small>Durable execution with citations and approval gates</small></span></div>
        <div className="agent-runtime-controls">
          <select aria-label="Agent" value={selectedAgentId} onChange={(event) => setAgentId(event.target.value)} disabled={!agents.data?.length}>
            {(agents.data || []).map((agent) => <option value={agent.id} key={agent.id}>{agent.display_name}</option>)}
          </select>
          <select aria-label="Execution mode" value={executionMode} onChange={(event) => setExecutionMode(event.target.value as "graph" | "single")}>
            <option value="graph">Durable task graph</option>
            <option value="single">Single compatibility job</option>
          </select>
          <button className="primary-action" onClick={() => void invoke(selectedAgentId, draft)} disabled={busy || !selectedAgentId || !prompt.trim()}><Play size={14} /> {busy ? "Running" : "Run agent"}</button>
        </div>
      </header>
      {agents.error ? <ErrorBanner message={agents.error instanceof Error ? agents.error.message : String(agents.error)} /> : null}
      {error ? <ErrorBanner message={error} /> : null}
      {!agents.isLoading && !agents.data?.length ? <p className="agent-runtime-empty">Create and configure an agent before running this decision flow.</p> : (
        <>
          <label className="agent-prompt-field">Instruction<textarea rows={2} value={prompt} onChange={(event) => setPrompt(event.target.value)} /></label>
          <div className="agent-parameter-editor">
            <div><strong>Action parameters</strong><button onClick={() => setParameters((rows) => [...rows, { id: crypto.randomUUID(), name: "", value: "" }])}><Plus size={14} /> Add parameter</button></div>
            {parameters.length ? parameters.map((row, index) => (
              <div className="agent-parameter-row" key={row.id}>
                <label>Name<input aria-label={`Parameter ${index + 1} name`} value={row.name} onChange={(event) => setParameters((rows) => rows.map((item) => item.id === row.id ? { ...item, name: event.target.value } : item))} placeholder="incident_id" /></label>
                <label>Value<input aria-label={`Parameter ${index + 1} value`} value={row.value} onChange={(event) => setParameters((rows) => rows.map((item) => item.id === row.id ? { ...item, value: event.target.value } : item))} /></label>
                <button aria-label={`Delete parameter ${index + 1}`} onClick={() => setParameters((rows) => rows.filter((item) => item.id !== row.id))}><Trash2 size={14} /></button>
              </div>
            )) : <small>No action parameters configured. Add only the typed values required by the selected agent tools.</small>}
          </div>
          {job ? (
            <div className="agent-job-state">
              <span><StatusBadge value={job.status} /><small>{job.job_type} · attempt {job.attempt}</small></span>
              <div className="agent-progress"><i style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }} /></div>
              <strong>{job.progress}%</strong>
              {["BLOCKED", "QUEUED", "RUNNING"].includes(job.status) ? <button onClick={() => void cancel()}><Ban size={14} /> Cancel</button> : null}
              {["FAILED", "CANCELLED"].includes(job.status) ? <button onClick={() => void retry()} disabled={busy}><RotateCcw size={14} /> Retry</button> : null}
            </div>
          ) : null}
          {job?.agent_task_graph ? (
            <div className="agent-task-graph" aria-label="Agent task graph">
              <div>
                <strong>Task graph</strong>
                <small>{job.agent_task_graph.tool_count} independently retryable tool stage{job.agent_task_graph.tool_count === 1 ? "" : "s"}</small>
              </div>
              <DataTable rows={[
                ...graphStages.map((stage, index) => ({
                  stage: stage.job_type === "aip.agent.context" ? "Context" : `Tool ${index}`,
                  job: stage.id,
                  status: stage.status,
                  attempt: stage.attempt
                })),
                { stage: "Synthesis", job: job.id, status: job.status, attempt: job.attempt }
              ]} empty="Task stages are loading." />
            </div>
          ) : null}
          {result ? (
            <div className="agent-run-evidence">
              <div className="agent-answer"><StatusBadge value={policy} /><p>{result.answer}</p><small>{result.retrieval.retrieved_object_count || 0} objects retrieved · {result.tool_calls.length} tools · {result.policy_summary.direct_mutations || 0} direct mutations</small></div>
              <div className="agent-tool-trace">
                {result.tool_calls.map((call, index) => (
                  <article key={`${call.tool}-${index}`}>
                    <span><strong>{call.tool}</strong><small>{call.type} · {call.duration_ms} ms</small></span>
                    <StatusBadge value={call.policy_decision} />
                    <small>{call.citations.length} citation{call.citations.length === 1 ? "" : "s"}</small>
                  </article>
                ))}
              </div>
              {result.proposed_actions.map((action, index) => (
                <div className="agent-proposal" key={`${action.action_type_id}-${index}`}>
                  <span><strong>{action.action_type_id}</strong><small>{action.approval_request_id ? `Approval ${action.approval_request_id}` : "Staged for review"}</small></span>
                  <StatusBadge value={action.policy_decision} />
                </div>
              ))}
            </div>
          ) : null}
          {events.length ? <div className="agent-event-strip">{events.map((event) => <span key={event.id}>{event.event_type.replace("job.", "")}</span>)}</div> : null}
        </>
      )}
    </section>
  );
}
