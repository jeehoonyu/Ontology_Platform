import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Check, GitCompareArrows, Play, RefreshCw, Search, ShieldAlert, Sparkles, X } from "lucide-react";
import { DataTable, EmptyState, ErrorBanner, KeyValueGrid, LoadingState, Metric, Panel, StatusBadge } from "../components/data/DataDisplay";
import { Page } from "../components/workbench/Workbench";
import { AgentRuntimePanel } from "./AgentRuntimePanel";
import { listObjectTypes, type ObjectTypeSummary } from "../api/objectExplorerApi";
import {
  acceptEntityCandidate, bootstrapDecision, createDecisionScenario, createEntityJob, evaluateDecision,
  explainDecisionObject, getObjectTimeline, listDecisionRules, listDecisionScorecards, rejectEntityCandidate,
  type DecisionEvaluation, type DecisionExplanation, type DecisionRule, type DecisionScenario,
  type DecisionScorecard, type EntityCandidate, type ObjectSnapshot
} from "../api/decisionApi";
import type { JsonValue, TableRow } from "../types";

type Tab = "risk" | "explain" | "timeline" | "entity" | "scenario" | "agent";
const TABS: Array<{ id: Tab; label: string }> = [
  { id: "risk", label: "Risk Board" }, { id: "explain", label: "Explain Object" },
  { id: "timeline", label: "Timeline" }, { id: "entity", label: "Entity Resolution" },
  { id: "scenario", label: "Scenario Simulator" }, { id: "agent", label: "Agent Plan" }
];
const splitFields = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);
function parsedValue(value: string): JsonValue {
  const trimmed = value.trim();
  if (trimmed.toLowerCase() === "true") return true;
  if (trimmed.toLowerCase() === "false") return false;
  const number = Number(trimmed);
  return trimmed !== "" && Number.isFinite(number) ? number : trimmed;
}

export function DecisionWorkspace() {
  const [tab, setTab] = useState<Tab>("risk");
  const [objectTypes, setObjectTypes] = useState<ObjectTypeSummary[]>([]);
  const [objectTypeId, setObjectTypeId] = useState("");
  const [rules, setRules] = useState<DecisionRule[]>([]);
  const [scorecards, setScorecards] = useState<DecisionScorecard[]>([]);
  const [evaluation, setEvaluation] = useState<DecisionEvaluation | null>(null);
  const [objectId, setObjectId] = useState("");
  const [explanation, setExplanation] = useState<DecisionExplanation | null>(null);
  const [timeline, setTimeline] = useState<ObjectSnapshot[]>([]);
  const [candidates, setCandidates] = useState<EntityCandidate[]>([]);
  const [scenario, setScenario] = useState<DecisionScenario | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const projectId = objectTypes.find((item) => item.id === objectTypeId)?.project_id || "default";

  const loadCatalog = useCallback(async (typeId: string, typeProjectId?: string) => {
    if (!typeId) return;
    const scopedProjectId = typeProjectId || objectTypes.find((item) => item.id === typeId)?.project_id || "default";
    const [nextRules, nextScorecards] = await Promise.all([listDecisionRules(scopedProjectId, typeId), listDecisionScorecards(scopedProjectId, typeId)]);
    setRules(nextRules); setScorecards(nextScorecards);
  }, [objectTypes]);
  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const types = await listObjectTypes();
      setObjectTypes(types);
      const nextId = types.some((item) => item.id === objectTypeId) ? objectTypeId : types[0]?.id || "";
      setObjectTypeId(nextId);
      await loadCatalog(nextId, types.find((item) => item.id === nextId)?.project_id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Decision workspace could not load"); }
    finally { setLoading(false); }
  }, [loadCatalog, objectTypeId]);
  useEffect(() => { void refresh(); }, []);
  const act = async (label: string, task: () => Promise<void>) => {
    setBusy(label); setError(""); setNotice("");
    try { await task(); setNotice(label); } catch (cause) { setError(cause instanceof Error ? cause.message : `${label} failed`); }
    finally { setBusy(""); }
  };
  const selectType = (nextId: string) => void act("Ontology context loaded", async () => {
    setObjectTypeId(nextId); setEvaluation(null); setObjectId(""); setExplanation(null); setTimeline([]); setCandidates([]); setScenario(null);
    await loadCatalog(nextId, objectTypes.find((item) => item.id === nextId)?.project_id);
  });
  const runEvaluation = () => void act("Risk evaluation completed", async () => {
    const result = await evaluateDecision(projectId, objectTypeId);
    setEvaluation(result); setObjectId(result.findings[0]?.object_id || ""); setTab("risk");
  });
  const updateCandidate = async (id: string, accept: boolean) => {
    const changed = accept ? await acceptEntityCandidate(id) : await rejectEntityCandidate(id);
    setCandidates((items) => items.map((item) => item.id === id ? changed : item));
  };
  const highCount = evaluation?.findings.filter((item) => ["high", "critical"].includes(item.risk.band.toLowerCase())).length || 0;
  const averageRisk = evaluation?.findings.length ? Math.round(evaluation.findings.reduce((sum, item) => sum + item.risk.score, 0) / evaluation.findings.length) : 0;

  if (loading) return <LoadingState label="Loading decision intelligence..." />;
  return <Page title="Decision Intelligence" subtitle="Explainable risk, temporal evidence, entity resolution, scenarios, and governed agent plans">
    <div className="decision-topbar">
      <label><span>Ontology object type</span><select aria-label="Decision object type" value={objectTypeId} onChange={(event) => selectType(event.target.value)}>{objectTypes.map((item) => <option key={item.id} value={item.id}>{item.display_name || item.id}</option>)}</select></label>
      <label><span>Selected object</span><input aria-label="Decision object ID" value={objectId} onChange={(event) => setObjectId(event.target.value)} placeholder="Select a finding or enter an ID" /></label>
      <button onClick={() => void refresh()} disabled={!!busy}><RefreshCw size={15} />Refresh</button>
      <button onClick={() => void act("Decision defaults created", async () => { await bootstrapDecision(projectId, objectTypeId); await loadCatalog(objectTypeId, projectId); })} disabled={!objectTypeId || !!busy}><Sparkles size={15} />Bootstrap rules</button>
      <button className="primary" onClick={runEvaluation} disabled={!objectTypeId || !!busy}><Play size={15} />Evaluate risk</button>
    </div>
    <ErrorBanner message={error} />
    {notice ? <div className="inline-success" role="status">{notice}</div> : null}
    <div className="decision-metrics"><Metric label="Objects evaluated" value={evaluation?.object_count || 0} /><Metric label="High-risk findings" value={highCount} /><Metric label="Average risk" value={averageRisk} /><Metric label="Active rules" value={rules.length} /><Metric label="Scorecards" value={scorecards.length} /></div>
    <nav className="decision-tabs" aria-label="Decision intelligence views">{TABS.map((item) => <button key={item.id} className={tab === item.id ? "active" : ""} onClick={() => setTab(item.id)}>{item.label}</button>)}</nav>
    {tab === "risk" ? <RiskBoard evaluation={evaluation} rules={rules} scorecards={scorecards} onSelect={(id) => { setObjectId(id); setTab("explain"); }} /> : null}
    {tab === "explain" ? <ExplainPanel objectId={objectId} explanation={explanation} busy={busy} onExplain={() => void act("Explanation loaded", async () => setExplanation(await explainDecisionObject(objectTypeId, objectId)))} /> : null}
    {tab === "timeline" ? <TimelinePanel objectId={objectId} timeline={timeline} busy={busy} onLoad={() => void act("Timeline loaded", async () => setTimeline((await getObjectTimeline(objectTypeId, objectId)).timeline))} /> : null}
    {tab === "entity" ? <EntityPanel candidates={candidates} busy={busy} onRun={(resolutionFields, threshold) => void act("Entity review queue generated", async () => setCandidates((await createEntityJob(projectId, objectTypeId, resolutionFields, threshold)).candidates || []))} onAccept={(id) => void act("Candidate accepted", () => updateCandidate(id, true))} onReject={(id) => void act("Candidate rejected", () => updateCandidate(id, false))} /> : null}
    {tab === "scenario" ? <ScenarioPanel objectId={objectId} scenario={scenario} busy={busy} onRun={(property, value) => void act("Scenario completed", async () => setScenario(await createDecisionScenario({ project_id: projectId, display_name: `Impact scenario for ${objectId}`, seed_object_ids: [objectId], overrides: { [objectId]: { [property]: parsedValue(value) } } })))} /> : null}
    {tab === "agent" ? <div className="decision-agent-wrap"><AgentRuntimePanel /></div> : null}
  </Page>;
}

function RiskBoard({ evaluation, rules, scorecards, onSelect }: { evaluation: DecisionEvaluation | null; rules: DecisionRule[]; scorecards: DecisionScorecard[]; onSelect: (id: string) => void }) {
  const sorted = useMemo(() => [...(evaluation?.findings || [])].sort((a, b) => b.risk.score - a.risk.score), [evaluation]);
  return <div className="decision-risk-layout"><Panel title="Risk Board" action={<ShieldAlert size={17} />}><div className="decision-risk-grid">{sorted.map((finding) => <button key={finding.object_id} onClick={() => onSelect(finding.object_id)}><header><strong>{String(finding.object.properties.name || finding.object.properties.title || finding.object_id)}</strong><StatusBadge value={finding.risk.band} /></header><span>{finding.object_id}</span><div className="decision-score"><b>{finding.risk.score}</b><span>risk score</span></div><p>{finding.risk.explanation}</p><footer>{finding.risk.drivers.slice(0, 3).map((driver, index) => <span key={index}>{driver.feature || driver.rule_id || "driver"}</span>)}</footer></button>)}</div>{!sorted.length ? <EmptyState title="No evaluated objects" description="Bootstrap decision rules, then evaluate the selected ontology type." /> : null}</Panel><aside><Panel title="Active Rules"><div className="decision-definition-list">{rules.map((rule) => <article key={rule.id}><span><strong>{rule.display_name}</strong><small>{String(rule.expression.field || "linked condition")} {String(rule.expression.op || "")}</small></span><StatusBadge value={rule.severity} /></article>)}</div>{!rules.length ? <div className="empty">No rules configured.</div> : null}</Panel><Panel title="Risk Scorecards"><div className="decision-definition-list">{scorecards.map((scorecard) => <article key={scorecard.id}><span><strong>{scorecard.display_name}</strong><small>{scorecard.features.length} weighted drivers</small></span><StatusBadge value={scorecard.active ? "active" : "disabled"} /></article>)}</div>{!scorecards.length ? <div className="empty">No scorecards configured.</div> : null}</Panel></aside></div>;
}

function ExplainPanel({ objectId, explanation, busy, onExplain }: { objectId: string; explanation: DecisionExplanation | null; busy: string; onExplain: () => void }) {
  const rows: TableRow[] = (explanation?.risk.drivers || []).map((driver) => ({ driver: driver.feature || driver.rule_id || "rule", reason: driver.reason || "Matched decision condition", weight: driver.weight || 0, contribution: driver.contribution || driver.weight || 0 }));
  return <div className="decision-evidence-layout"><Panel title="Object Explanation" action={<button className="primary" disabled={!objectId || !!busy} onClick={onExplain}><Search size={14} />Explain selected object</button>}>{explanation ? <><div className="decision-explain-heading"><div><strong>{String(explanation.object.properties.name || explanation.object.id)}</strong><span>{explanation.object.id}</span></div><div className="decision-score"><b>{explanation.risk.score}</b><StatusBadge value={explanation.risk.band} /></div></div><p className="decision-narrative">{explanation.explanation || explanation.risk.explanation}</p><DataTable rows={rows} empty="No active risk drivers" /></> : <EmptyState title="Choose an object to explain" description="Select a finding from the Risk Board or enter an object ID above." />}</Panel><Panel title="Recommended Actions">{explanation?.recommended_actions?.length ? <ol className="decision-action-list">{explanation.recommended_actions.map((action) => <li key={action}><Check size={14} />{action.replace(/_/g, " ")}</li>)}</ol> : <div className="empty">No recommendation loaded.</div>}<h3>Temporal context</h3>{explanation ? <KeyValueGrid data={explanation.temporal_summary} /> : <div className="empty">Explain an object to load temporal evidence.</div>}<h3>Duplicate warnings</h3><StatusBadge value={explanation?.duplicate_warnings?.length ? `${explanation.duplicate_warnings.length} warnings` : "clear"} /></Panel></div>;
}

function TimelinePanel({ objectId, timeline, busy, onLoad }: { objectId: string; timeline: ObjectSnapshot[]; busy: string; onLoad: () => void }) {
  return <Panel title="Object Activity Timeline" action={<button className="primary" disabled={!objectId || !!busy} onClick={onLoad}><Activity size={14} />Load timeline</button>}><div className="decision-timeline">{timeline.map((item) => <article key={item.id}><span className="decision-timeline-marker">{item.seq}</span><div><header><strong>{item.event_type.replace(/_/g, " ")}</strong><time>{new Date(item.created_at * 1000).toLocaleString()}</time></header><p>{item.actor} via {item.source_type || "platform"}{item.source_id ? ` · ${item.source_id}` : ""}</p><KeyValueGrid data={item.properties} /></div></article>)}</div>{!timeline.length ? <EmptyState title="No timeline loaded" description="Load append-only object snapshots for the selected object." /> : null}</Panel>;
}

function EntityPanel({ candidates, busy, onRun, onAccept, onReject }: { candidates: EntityCandidate[]; busy: string; onRun: (fields: string[], threshold: number) => void; onAccept: (id: string) => void; onReject: (id: string) => void }) {
  const [fieldText, setFieldText] = useState("name, serial_number"); const [threshold, setThreshold] = useState(70);
  return <div className="decision-evidence-layout"><Panel title="Resolution Settings"><label className="stacked-field"><span>Matching fields</span><input aria-label="Entity resolution fields" value={fieldText} onChange={(event) => setFieldText(event.target.value)} /></label><label className="stacked-field"><span>Minimum confidence: {threshold}%</span><input aria-label="Entity resolution threshold" type="range" min="40" max="100" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} /></label><button className="primary" disabled={!!busy || !splitFields(fieldText).length} onClick={() => onRun(splitFields(fieldText), threshold)}><GitCompareArrows size={15} />Find duplicates</button></Panel><Panel title="Candidate Review Queue"><div className="decision-candidate-list">{candidates.map((candidate) => <article key={candidate.id}><header><span><strong>{candidate.object_ids.join(" + ")}</strong><small>{candidate.reasons.length} matching signals</small></span><StatusBadge value={`${candidate.score}%`} /></header><div className="button-row"><button disabled={candidate.status !== "PENDING" || !!busy} onClick={() => onAccept(candidate.id)}><Check size={14} />Accept merge</button><button disabled={candidate.status !== "PENDING" || !!busy} onClick={() => onReject(candidate.id)}><X size={14} />Reject</button><StatusBadge value={candidate.status} /></div></article>)}</div>{!candidates.length ? <EmptyState title="No candidates" description="Choose matching fields and generate a deterministic review queue." /> : null}</Panel></div>;
}

function ScenarioPanel({ objectId, scenario, busy, onRun }: { objectId: string; scenario: DecisionScenario | null; busy: string; onRun: (property: string, value: string) => void }) {
  const [property, setProperty] = useState("status"); const [value, setValue] = useState("DEGRADED");
  const rows: TableRow[] = scenario?.impact.changed_object_ids.map((id) => ({ object_id: id, changed_properties: Object.keys(scenario.impact.by_object[id]?.properties || {}).join(", "), outcome: "changed" })) || [];
  return <div className="decision-evidence-layout"><Panel title="Scenario Inputs"><label className="stacked-field"><span>Seed object</span><input value={objectId} readOnly aria-label="Scenario seed object" /></label><div className="form-grid"><label><span>Override property</span><input aria-label="Scenario override property" value={property} onChange={(event) => setProperty(event.target.value)} /></label><label><span>Override value</span><input aria-label="Scenario override value" value={value} onChange={(event) => setValue(event.target.value)} /></label></div><button className="primary" disabled={!objectId || !property.trim() || !!busy} onClick={() => onRun(property.trim(), value)}><Play size={15} />Run impact scenario</button></Panel><Panel title="Before / After Impact" action={scenario ? <StatusBadge value={`${scenario.impact.changed_object_count} changed`} /> : null}>{scenario ? <><DataTable rows={rows} empty="Scenario produced no object changes" /><div className="decision-scenario-counts"><Metric label="Seed objects" value={scenario.seed_object_ids.length} /><Metric label="Changed objects" value={scenario.impact.changed_object_count} /></div></> : <EmptyState title="No scenario run" description="Override one property to compare deterministic before-and-after impact." />}</Panel></div>;
}
