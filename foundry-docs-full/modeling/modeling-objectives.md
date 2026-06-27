<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · MODELING</b><br>
<span style="font-size:22px"><b>Modeling Objectives</b></span><br>
<span style="color:#ABB3BF">Mission control for the full ML model lifecycle: submission, evaluation, review, release, and deployment — all governed around a single operational problem.</span>
</td></tr></table>

## What it is

A **Modeling Objective** is a Foundry resource that acts as the system of record for an ML modeling problem. It centralizes the problem definition, evaluation datasets, submission history, metrics, releases, and deployments into a single governed workspace. Rather than treating a model as a one-time artifact, Modeling Objectives frame it as an ongoing solution to a well-defined interface — successive model versions compete against the same evaluation criteria over time, enabling structured comparison, review, and operationalization with full lineage and auditability.

## How it works

Modeling Objectives impose a CI/CD-style pipeline on top of ML model artifacts. Every object in the system maps to a concrete Foundry resource with strict versioning and lineage.

1. **Define the objective.** A team creates a new Modeling Objective resource (stored in a Compass project folder) and writes a Markdown description of the problem. They configure the **API definition** — the expected input schema and output schema that all model submissions must conform to. This interface is the contract; models are implementations.

2. **Configure evaluation.** The objective is linked to an evaluation dataset containing both features and ground-truth labels. A `MetricSet` configuration maps model outputs (e.g., `prediction`) to ground-truth fields (e.g., `median_house_value`) and selects an evaluator library (e.g., Foundry's default regression evaluator). Optional **evaluation subsets** slice the dataset into segments (by region, date range, customer tier, etc.) so performance disparity across groups is surfaced automatically.

3. **Submit a model.** A data scientist submits a trained model (from Model Studio, a notebook, or an external artifact) to the objective. Submission creates an **immutable snapshot** of the model — analogous to opening a pull request. The submission triggers automatic builds of two downstream pipelines: an **inference pipeline** (runs the model against the evaluation dataset and writes predictions) and a **metrics pipeline** (reads predictions + labels and writes a `MetricSet` to a tracked output folder).

4. **Review and compare.** The objective's **evaluation dashboard** renders all `MetricSet` outputs side-by-side across submissions. Reviewers can compare overall metrics and per-subset breakdowns, inspect charts and images embedded in the `MetricSet`, and drill into individual predictions. **Quality Assurance (QA) checks** — pre-configured numeric thresholds — automatically pass or fail each submission before it can be released.

5. **Create a release.** Once a submission passes QA and review, a maintainer promotes it to a **Release**: a versioned, packaged, production-ready asset. Releases carry an environment tag (`staging` or `production`), a user-defined semantic version number, and optional release notes. Releases are the units consumed by deployments — deployments do not reference raw submissions directly.

6. **Deploy.** Releases are wired into one or more **Deployments**:
   - **Batch deployment** — a Foundry pipeline that reads an input dataset, runs the released model, and writes predictions to an output dataset. Configurable to rebuild automatically whenever the underlying dataset receives new logic or data, keeping predictions continuously fresh.
   - **Live deployment** — a serverless REST endpoint (backed by a continually running server) that accepts JSON payloads and returns real-time predictions. Integrates with Foundry Functions on Models, external systems, or direct CURL calls. Note: live deployments are not terminated automatically and incur ongoing compute costs.
   - **Python Transforms** — lightweight inline batch inference embedded directly in a code repository transform.

7. **Version upgrades without downtime.** When a new release is tagged with an existing environment label (e.g., `production`), deployments automatically pick up the new model version without downtime, while preserving full lineage back to the original submission and training data.

Throughout the entire flow, Foundry enforces **lineage, security, versioning, reproducibility, and auditing** — every inference trace back to the exact model artifact, dataset version, and code commit that produced it.

## User interface

The Modeling Objectives application is accessed from the Foundry sidebar. Its layout follows the standard Foundry dark-panel design.

**Main navigation** — a left sidebar lists all objectives the user has access to. Clicking an objective opens its home page, which shows the description (Markdown-rendered), a summary of recent submissions, and quick-links to deployments and releases.

**Submissions tab** — a table of all model submissions sorted by timestamp, with columns for submitter, QA check status, and a link to the evaluation dashboard for that submission.

**Evaluation dashboard** — the primary analytical surface. Metrics for each submission are rendered as cards with numeric values, bar charts, and images. Subset tabs (one per configured evaluation segment) appear in a horizontal tab bar at the top. A comparison mode lets users pin two or more submissions side-by-side.

**Releases tab** — lists all versioned releases with environment badges and release notes. The <span style="color:#2D72D2"><b>New Release</b></span> button opens a modal to select a submission, assign a version string, choose `staging` or `production`, and add notes.

**Deployments tab** — shows all batch and live deployments wired to this objective. Each entry displays its type, status, and the release version it is currently serving.

**Settings panel** (gear icon) — exposes all objective-level configuration:

<table style="border-collapse:collapse;width:100%;background:#1C2127;color:#fff;font-size:13px">
<tr style="border-bottom:1px solid #383E47">
  <th style="padding:8px 12px;text-align:left;color:#ABB3BF">Setting</th>
  <th style="padding:8px 12px;text-align:left;color:#ABB3BF">What it controls</th>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#8ABBFF"><b>Checks</b></span></td>
  <td style="padding:8px 12px">QA thresholds a submission must pass before it can be released</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#8ABBFF"><b>Deployments</b></span></td>
  <td style="padding:8px 12px">Deployment profile requirements for Python submissions (batch/live prerequisites)</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#8ABBFF"><b>Model Metadata</b></span></td>
  <td style="padding:8px 12px">Mandatory metadata fields collected at submission time for governance and comparison</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#8ABBFF"><b>Evaluation Dashboard</b></span></td>
  <td style="padding:8px 12px">Toggle to show only evaluation-config metrics; toggle to show pinned tabs</td>
</tr>
<tr>
  <td style="padding:8px 12px"><span style="color:#8ABBFF"><b>Appearance</b></span></td>
  <td style="padding:8px 12px">Light / dark mode for this objective</td>
</tr>
</table>

**Status chips used across the UI:**

<span style="color:#238551"><b>● passing</b></span> · <span style="color:#CD4246"><b>● failed QA</b></span> · <span style="color:#C87619"><b>● building / pending</b></span> · <span style="color:#2D72D2"><b>● production</b></span> · <span style="color:#9D3F9D"><b>● staging</b></span>

## Worked example

**Scenario: A logistics team wants to predict delivery delay risk for a fleet of 50,000 daily shipments.**

1. A data engineer creates a Modeling Objective called *Delivery Delay Risk* in the `Logistics/Models` Compass folder and writes a Markdown description of the SLA requirements.

2. They configure the API: input schema = `{shipment_id, origin_zip, destination_zip, carrier, weight_kg}`, output schema = `{shipment_id, delay_probability}`.

3. They link an evaluation dataset of 90-day historical shipments with ground-truth delay flags, and configure a binary classification evaluator mapping `delay_probability → actual_delayed`.

4. They add two QA checks: `AUC >= 0.80` and `Precision@0.5 >= 0.70`.

5. A data scientist trains a gradient-boosted model in Model Studio and submits it. Foundry automatically runs inference and metrics pipelines and posts the `MetricSet` to the evaluation dashboard. AUC = 0.84 — QA passes (<span style="color:#238551"><b>● passing</b></span>).

6. The team lead reviews the subset breakdown by carrier and confirms performance is consistent. They create Release `v1.0.0` tagged `production`.

7. A **batch deployment** is created: input = daily shipments dataset, output = `delay_predictions/` folder. It is scheduled to rebuild nightly. A downstream Foundry Workshop application reads predictions and surfaces high-risk shipments to the dispatch team each morning.

## Documentation map

- **Core concepts** — modeling objective, submission, release, deployment, MetricSet definitions
- **Create a modeling objective** — UI walkthrough for initial setup and description
- **Define modeling objective API** — configuring the input/output schema contract
- **Modeling objective settings** — checks, deployment profiles, metadata fields, dashboard toggles
- **Tutorial: Set up a machine learning project** — end-to-end project initialization
- **Tutorial: Evaluate a model in Modeling Objectives** — configuring evaluation, running builds, reading the dashboard
- **Tutorial: Productionize a model** — creating releases, configuring batch and live deployments
- **Model Integration overview** — the broader model lifecycle context (sources, objectives, ontology integration)
- **Core concepts: Models** — model artifacts, Model Studio, experiments, functions

## Official documentation

- [Core concepts · Modeling Objectives](https://www.palantir.com/docs/foundry/model-integration/objectives)
- [Model Integration overview](https://www.palantir.com/docs/foundry/model-integration)
- [Create a modeling objective](https://www.palantir.com/docs/foundry/manage-models/create-a-modeling-objective)
- [Modeling objective settings](https://www.palantir.com/docs/foundry/manage-models/modeling-objective-settings)
- [Define modeling objective API](https://www.palantir.com/docs/foundry/manage-models/define-modeling-objective-api)
- [Tutorial: Evaluate a model in Modeling Objectives](https://www.palantir.com/docs/foundry/model-integration/tutorial-evaluate-manage-models)
- [Tutorial: Productionize a model](https://www.palantir.com/docs/foundry/model-integration/tutorial-productionize)
- [Tutorial: Set up a machine learning project](https://www.palantir.com/docs/foundry/model-integration/tutorial-set-up-project)
