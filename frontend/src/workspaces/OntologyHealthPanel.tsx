import { useCallback, useEffect, useMemo, useState } from "react";
import {
  generateStandardObjectView,
  getOntologyHealthUiState,
  runOntologyHealth,
  simulateOntologyPolicy,
  type OntologyHealthFinding,
  type OntologyHealthUiState,
  type OntologyPolicyDecision
} from "../api/ontologyHealthApi";
import { Panel, StatusBadge } from "../components/data/DataDisplay";

const SEVERITIES = ["ALL", "ERROR", "WARN", "INFO"] as const;

export function OntologyHealthPanel({ objectTypeId, onBack }: { objectTypeId: string; onBack: () => void }) {
  const [state, setState] = useState<OntologyHealthUiState | null>(null);
  const [severity, setSeverity] = useState<(typeof SEVERITIES)[number]>("ALL");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [principal, setPrincipal] = useState("analyst");
  const [action, setAction] = useState("view");
  const [purpose, setPurpose] = useState("operations");
  const [effect, setEffect] = useState<"ALLOW" | "DENY" | "MASK" | "ROW_FILTER" | "REQUIRE_APPROVAL">("DENY");
  const [policyDecision, setPolicyDecision] = useState<OntologyPolicyDecision | null>(null);

  const refresh = useCallback(async () => {
    setState(await getOntologyHealthUiState(objectTypeId));
  }, [objectTypeId]);

  useEffect(() => {
    setMessage("");
    setPolicyDecision(null);
    void refresh().catch((error) => setMessage(error instanceof Error ? error.message : "Could not load ontology health."));
  }, [refresh]);

  const findings = useMemo(() => (state?.sections.findings || []).filter((item) => severity === "ALL" || item.severity === severity), [severity, state]);

  async function runHealth() {
    setBusy(true);
    try {
      const result = await runOntologyHealth(objectTypeId);
      setMessage(`Health evaluation completed: ${result.status} with score ${result.score}.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not run ontology health.");
    } finally {
      setBusy(false);
    }
  }

  async function generateView() {
    setBusy(true);
    try {
      const result = await generateStandardObjectView(objectTypeId);
      setMessage(result.created ? "Standard object view generated and published." : "A configured object view already exists.");
      await runOntologyHealth(objectTypeId);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not generate object view.");
    } finally {
      setBusy(false);
    }
  }

  async function simulate() {
    setBusy(true);
    try {
      const result = await simulateOntologyPolicy(objectTypeId, { principal, action, purpose, effect });
      setPolicyDecision(result.decision);
      setMessage("Policy simulation completed without changing active policy rules.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not simulate policy.");
    } finally {
      setBusy(false);
    }
  }

  const summary = state?.summary;
  const metrics = state?.sections.metrics || {};
  return (
    <section className="ontology-health-center" aria-labelledby="ontology-health-title">
      <header className="manager-header-card ontology-health-header">
        <div>
          <span className="object-icon">HC</span>
          <h2 id="ontology-health-title">Ontology Health Center</h2>
          <p>Validate identity, schema, runtime values, relationships, lineage, views, and governance.</p>
          <div className="manager-chip-row"><StatusBadge value={summary?.status || "NOT_RUN"} /><span>{objectTypeId}</span></div>
        </div>
        <div className="button-row">
          <button onClick={onBack}>Back to object</button>
          <button className="primary" onClick={runHealth} disabled={busy}>Run health check</button>
        </div>
      </header>
      {message ? <div className="operation-message" role="status">{message}</div> : null}

      <div className="ontology-health-score-grid">
        <div className="health-score"><span>Health score</span><strong>{summary?.score ?? "-"}</strong><StatusBadge value={summary?.status || "NOT_RUN"} /></div>
        <div><span>Errors</span><strong>{summary?.errors || 0}</strong></div>
        <div><span>Warnings</span><strong>{summary?.warnings || 0}</strong></div>
        <div><span>Objects</span><strong>{metrics.objects ?? 0}</strong></div>
        <div><span>Type conformance</span><strong>{formatPercent(metrics.type_conformance)}</strong></div>
        <div><span>Lineage coverage</span><strong>{formatPercent(metrics.lineage_coverage)}</strong></div>
      </div>

      <div className="ontology-health-main-grid">
        <Panel title="Findings" className="ontology-health-findings" action={<div className="segmented-control" aria-label="Finding severity">{SEVERITIES.map((item) => <button key={item} className={severity === item ? "active" : ""} onClick={() => setSeverity(item)}>{item}</button>)}</div>}>
          {findings.length ? findings.map((finding) => <FindingRow key={finding.id} finding={finding} onGenerateView={finding.code === "MISSING_OBJECT_VIEW" ? generateView : undefined} busy={busy} />) : <div className="health-empty"><strong>{summary?.status === "PASS" ? "No active findings" : "Run a health check"}</strong><span>{summary?.status === "PASS" ? "Identity, schema, values, lineage, and governance checks passed." : "Evaluate this object type to produce actionable evidence."}</span></div>}
        </Panel>

        <Panel title="Policy Simulator" className="ontology-policy-simulator" action={<StatusBadge value={policyDecision?.decision || "WHAT_IF"} />}>
          <p>Test a hypothetical rule without changing production policy.</p>
          <div className="policy-simulator-form">
            <label><span>Principal</span><input value={principal} onChange={(event) => setPrincipal(event.target.value)} /></label>
            <label><span>Action</span><select value={action} onChange={(event) => setAction(event.target.value)}><option>view</option><option>edit</option><option>execute</option><option>publish</option><option>export</option></select></label>
            <label><span>Purpose</span><input value={purpose} onChange={(event) => setPurpose(event.target.value)} /></label>
            <label><span>Hypothetical effect</span><select value={effect} onChange={(event) => setEffect(event.target.value as typeof effect)}><option>DENY</option><option>ALLOW</option><option>REQUIRE_APPROVAL</option><option>MASK</option><option>ROW_FILTER</option></select></label>
            <button onClick={simulate} disabled={busy || !principal.trim()}>Simulate</button>
          </div>
          {policyDecision ? <div className="policy-decision-card"><div><StatusBadge value={policyDecision.decision} /><strong>{policyDecision.allowed ? "Allowed" : "Blocked"}</strong></div><p>{policyDecision.explanation}</p><small>{policyDecision.matched_rule_ids.length} matching rule{policyDecision.matched_rule_ids.length === 1 ? "" : "s"}</small></div> : null}
        </Panel>
      </div>
    </section>
  );
}

function FindingRow({ finding, onGenerateView, busy }: { finding: OntologyHealthFinding; onGenerateView?: () => void; busy: boolean }) {
  return <article className={`ontology-health-finding severity-${finding.severity.toLowerCase()}`}>
    <StatusBadge value={finding.severity} />
    <div><strong>{finding.title}</strong><p>{finding.detail}</p><small>{finding.recommendation}</small></div>
    <div className="finding-meta"><span>{finding.category.replace(/_/g, " ")}</span>{finding.count > 1 ? <span>{finding.count} affected</span> : null}{onGenerateView ? <button onClick={onGenerateView} disabled={busy}>Generate view</button> : null}</div>
  </article>;
}

function formatPercent(value: number | undefined): string {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "-";
}
