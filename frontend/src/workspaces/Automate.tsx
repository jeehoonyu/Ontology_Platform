import { useEffect, useState } from "react";
import {
  createAutomation,
  getAutomationActivities,
  getAutomationDetail,
  getAutomationHistory,
  listAutomations,
  muteAutomation,
  pauseAutomation,
  resumeAutomation,
  runAutomation,
  unmuteAutomation
} from "../api/automateApi";
import type {
  AutomationActivity,
  AutomationDetail,
  AutomationHistory,
  AutomationRunResult
} from "../api/automateApi";
import {
  DataTable,
  EmptyState,
  ErrorBanner,
  KeyValueGrid,
  LoadingState,
  Metric,
  Panel,
  StatusBadge
} from "../components/data/DataDisplay";
import { Page } from "../components/workbench/Workbench";
import { useAsyncState } from "../hooks/useAsyncState";
import { asString, classNames, formatValue } from "../utils/format";
import type { JsonObject, TableRow } from "../types";

const SCOPE_MODES = ["user_scoped", "project_scoped"];

function summarizeConfig(config: JsonObject | undefined): string {
  const entries = Object.entries(config || {});
  if (!entries.length) return "-";
  return entries.map(([key, value]) => `${key}=${formatValue(value)}`).join(", ");
}

function formatTimestamp(seconds: number | null | undefined): string {
  if (!seconds) return "-";
  return new Date(seconds * 1000).toLocaleString();
}

export function Automate() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [scopeMode, setScopeMode] = useState("user_scoped");
  const [enabled, setEnabled] = useState(true);
  const [description, setDescription] = useState("");
  const [actionError, setActionError] = useState("");
  const [lastRun, setLastRun] = useState<AutomationRunResult | null>(null);

  const automations = useAsyncState(listAutomations, [refreshKey]);
  const detail = useAsyncState<AutomationDetail | null>(
    () => (selectedId ? getAutomationDetail(selectedId) : Promise.resolve(null)),
    [selectedId, refreshKey]
  );
  const history = useAsyncState<AutomationHistory | null>(
    () => (selectedId ? getAutomationHistory(selectedId) : Promise.resolve(null)),
    [selectedId, refreshKey]
  );
  const activities = useAsyncState<AutomationActivity[]>(
    () => (selectedId ? getAutomationActivities(selectedId) : Promise.resolve([])),
    [selectedId, refreshKey]
  );

  const rows = automations.value || [];

  useEffect(() => {
    if (!selectedId && rows.length) {
      setSelectedId(asString(rows[0].id));
    }
  }, [rows, selectedId]);

  function selectAutomation(id: string) {
    setSelectedId(id);
    setLastRun(null);
    setActionError("");
  }

  async function runAction(fn: () => Promise<unknown>) {
    setActionError("");
    try {
      await fn();
      setRefreshKey((key) => key + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  }

  async function submitCreate() {
    const name = displayName.trim();
    if (!name) return;
    setActionError("");
    try {
      const created = await createAutomation({
        display_name: name,
        scope_mode: scopeMode,
        enabled,
        description: description.trim() || undefined
      });
      setDisplayName("");
      setDescription("");
      selectAutomation(asString(created.id));
      setRefreshKey((key) => key + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  }

  async function runSelected() {
    if (!selectedId) return;
    setActionError("");
    try {
      const result = await runAutomation(selectedId);
      setLastRun(result);
      setRefreshKey((key) => key + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  }

  const automation = detail.value?.automation || null;
  const enabledCount = rows.filter((row) => row.enabled).length;
  const mutedCount = rows.filter((row) => row.muted).length;

  const conditionRows: TableRow[] = (detail.value?.conditions || []).map((condition) => ({
    id: condition.id,
    condition_type: condition.condition_type,
    config: summarizeConfig(condition.config)
  }));
  const effectRows: TableRow[] = (detail.value?.effects || []).map((effect) => ({
    id: effect.id,
    effect_type: effect.effect_type,
    order: effect.execution_order,
    parent: effect.parent_effect_id || "-",
    config: summarizeConfig(effect.config)
  }));
  const activityRows: TableRow[] = (activities.value || []).map((activity) => ({
    event: activity.event_type,
    detail: summarizeConfig(activity.payload),
    at: formatTimestamp(activity.created_at)
  }));
  const runs = history.value?.runs || [];

  return (
    <Page title="Automate" subtitle="Trigger, pause, mute, and audit ontology automations and their run history.">
      <ErrorBanner message={automations.error || actionError} />
      {automations.loading && <LoadingState label="Loading automations..." />}

      <div className="grid metrics">
        <Metric label="Automations" value={rows.length} />
        <Metric label="Enabled" value={enabledCount} />
        <Metric label="Paused" value={rows.length - enabledCount} />
        <Metric label="Muted" value={mutedCount} />
      </div>

      <div className="two-col">
        <Panel
          title="Automations"
          action={<button onClick={() => setRefreshKey((key) => key + 1)}>Refresh</button>}
        >
          {rows.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Automation</th>
                    <th>Scope</th>
                    <th>State</th>
                    <th>Muted</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const id = asString(row.id);
                    return (
                      <tr
                        key={id}
                        className={classNames(selectedId === id && "selected")}
                        onClick={() => selectAutomation(id)}
                        style={{ cursor: "pointer" }}
                      >
                        <td title={id}>{asString(row.display_name, id)}</td>
                        <td>{asString(row.scope_mode)}</td>
                        <td><StatusBadge value={row.enabled ? "enabled" : "paused"} /></td>
                        <td><StatusBadge value={row.muted ? "muted" : "unmuted"} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No automations yet" description="Create your first automation to get started." />
          )}
        </Panel>

        <Panel title="Create Automation">
          <div style={{ display: "grid", gap: 10 }}>
            <label>
              <span>Display name</span>
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="Escalate degraded assets"
              />
            </label>
            <label>
              <span>Scope mode</span>
              <select value={scopeMode} onChange={(event) => setScopeMode(event.target.value)}>
                {SCOPE_MODES.map((mode) => <option key={mode} value={mode}>{mode}</option>)}
              </select>
            </label>
            <label>
              <span>Description</span>
              <input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Optional description"
              />
            </label>
            <label>
              <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
              Enabled on create
            </label>
            <div className="button-row">
              <button onClick={submitCreate} disabled={!displayName.trim()}>Create automation</button>
            </div>
          </div>
        </Panel>
      </div>

      {selectedId ? (
        <>
          <div className="two-col">
            <Panel
              title="Automation Detail"
              action={
                <div className="button-row">
                  <button onClick={runSelected}>Run</button>
                  <button disabled={!automation?.enabled} onClick={() => runAction(() => pauseAutomation(selectedId))}>Pause</button>
                  <button disabled={!!automation && automation.enabled} onClick={() => runAction(() => resumeAutomation(selectedId))}>Resume</button>
                  <button disabled={!!automation && automation.muted} onClick={() => runAction(() => muteAutomation(selectedId))}>Mute</button>
                  <button disabled={!automation?.muted} onClick={() => runAction(() => unmuteAutomation(selectedId))}>Unmute</button>
                </div>
              }
            >
              {detail.error ? <ErrorBanner message={detail.error} /> : null}
              {automation ? (
                <>
                  <div className="button-row" style={{ marginBottom: 10 }}>
                    <StatusBadge value={automation.enabled ? "enabled" : "paused"} />
                    <StatusBadge value={automation.muted ? "muted" : "unmuted"} />
                    <StatusBadge value={automation.scope_mode} />
                  </div>
                  <KeyValueGrid
                    data={{
                      id: automation.id,
                      display_name: automation.display_name,
                      description: automation.description || "",
                      scope_mode: automation.scope_mode,
                      enabled: automation.enabled,
                      muted: automation.muted,
                      owner: automation.owner,
                      last_evaluated_at: formatTimestamp(automation.last_evaluated_at)
                    }}
                  />
                  {lastRun ? (
                    <div className="button-row" style={{ marginTop: 10 }}>
                      <span>Last run</span>
                      <StatusBadge value={lastRun.status} />
                      <span>{formatValue(lastRun.triggered_object_ids)} triggered</span>
                    </div>
                  ) : null}
                </>
              ) : (
                <EmptyState title="Select an automation" description="Choose an automation to inspect its condition and effects." />
              )}
            </Panel>

            <Panel title="Conditions and Effects">
              <h3>Conditions</h3>
              <DataTable rows={conditionRows} empty="No conditions configured." />
              <h3 style={{ marginTop: 12 }}>Effects</h3>
              <DataTable rows={effectRows} empty="No effects configured." />
            </Panel>
          </div>

          <div className="two-col">
            <Panel title="Run History">
              {runs.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Run</th>
                        <th>Status</th>
                        <th>Trigger</th>
                        <th>Mode</th>
                        <th>Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runs.map((run) => (
                        <tr key={run.id}>
                          <td title={run.id}>{run.id.slice(0, 8)}</td>
                          <td><StatusBadge value={run.status} /></td>
                          <td>{run.condition_result ? "triggered" : "skipped"}</td>
                          <td>{run.manual ? "manual" : "auto"}</td>
                          <td>{formatTimestamp(run.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState title="No runs yet" description="Run this automation to record run history." />
              )}
            </Panel>

            <Panel title="Activity">
              <DataTable rows={activityRows} empty="No activity recorded yet." />
            </Panel>
          </div>
        </>
      ) : null}
    </Page>
  );
}
