<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · MODELING</b><br>
<span style="font-size:22px"><b>Model Deployments (Live &amp; Batch)</b></span><br>
<span style="color:#ABB3BF">Serve trained model releases as real-time REST endpoints or scheduled batch inference pipelines inside a Modeling Objective.</span>
</td></tr></table>

## What it is

Model Deployments are the delivery layer of a **Modeling Objective**: they take a versioned, packaged model **release** and make it available either as a continuously running REST API (Live) or as a managed Foundry transform that writes predictions to a dataset (Batch). Both types inherit the Objective's governance — lineage, auditable version history, and the ability to automatically pick up new releases — so that upgrading a model in production requires no manual rewiring of downstream consumers.

There is also a lighter-weight **Direct Model Deployment** path that skips the Objective scaffolding and connects a model branch straight to a live endpoint, trading governance features for zero-friction instant hosting.

---

## How it works

### Core objects

| Object | Role |
|---|---|
| **Modeling Objective** | Container scoping the problem; holds submissions, releases, and deployments |
| **Submission** | Immutable snapshot of model code, created like a pull request |
| **Release** | Versioned, production-ready package with an environment tag (`Staging` or `Production`) and release notes |
| **Live Deployment** | Persistent container-backed REST endpoint tied to a release environment |
| **Batch Deployment** | Foundry transform (Spark job) that reads an input dataset, runs inference, and writes to an output dataset |

### Live deployment mechanics

1. **Release prerequisite.** A release tagged `Staging` or `Production` must exist inside the Objective before a live deployment can be created.
2. **Container build.** On creation Foundry builds a container image containing the model code, the serialized model artifact, and all inference dependencies. This build is surfaced as service logs in the UI.
3. **Replica pool.** The deployment starts with **2 replicas** by default, ensuring zero-downtime rolling upgrades. Replica count, CPU, and GPU allocations are all user-configurable and can be edited post-creation (each edit triggers a rolling redeployment).
4. **Endpoint activation.** Once healthy, Foundry registers a stable RID-based URL:
   `<ENV_URL>/foundry-ml-live/api/inference/transform/ri.foundry-ml-live.<RID>/v2`
   All requests use `Authorization: Bearer <token>` + `Content-Type: application/json`.
5. **Automatic version rollover.** When a new model is released to the same environment tag, the deployment automatically upgrades with no downtime — consumers keep calling the same URL.
6. **Query modes.** The **Multi I/O endpoint** (current standard) accepts named JSON fields matching the `ModelAdapter` input/output signature. The older **Single I/O endpoint** wraps data inside `requestData`/`responseData` envelopes and is deprecated.
7. **Lifecycle controls.** Deployments can be **Disabled** (endpoint goes dark, RID preserved) or **Deleted** (permanent). Neither action removes the underlying release.

### Batch deployment mechanics

1. **Release prerequisite.** Same as live: a `Staging` or `Production` release must exist.
2. **Transform creation.** Foundry auto-generates a Spark transform that reads a user-specified **input dataset**, runs the model's inference code via a Spark profile, and writes predictions to a user-specified **output dataset**.
3. **Single-tabular constraint.** The direct batch setup wizard only supports models with a single tabular input. Multi-input models must implement batch inference manually inside a Python transform.
4. **Build trigger.** The output dataset's logic updates whenever a new model is released to the deployment's environment. A **logic schedule** on the output dataset then rebuilds it automatically, so downstream pipelines always see fresh predictions without any manual intervention.
5. **Resource configuration.** Compute is controlled via **Spark profiles** selected at creation time and editable afterward from the deployment's Runtime configuration panel.

### Direct model deployment (lightweight path)

Direct deployments skip the Objective entirely. A user navigates to a model artifact, clicks **Start Deployment**, and Foundry creates a live endpoint that auto-upgrades whenever a new version is published to that branch. Auto-scaling (0 → max replicas at 75% capacity), type-safety enforcement on request fields, and a TypeScript Function wrapper for Workshop/Slate integration are all built in. The trade-off: no inference history, no pre-release review, no external model support.

---

## User interface

### Overall layout

The Modeling Objective home page has a top-level tab bar. Selecting **Deployments** opens a panel listing all live and batch deployments. From here users create, inspect, and manage deployments.

<table style="border-collapse:collapse;width:100%">
<tr style="background:#1C2127;color:#ABB3BF">
<th style="padding:8px 12px;border:1px solid #383E47;text-align:left">Screen / Panel</th>
<th style="padding:8px 12px;border:1px solid #383E47;text-align:left">What you see &amp; do</th>
</tr>
<tr style="background:#252A31">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Deployments list</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Cards for each deployment showing name, type (Live / Batch), environment tag, and status chip. <span style="color:#238551"><b>● Active</b></span> · <span style="color:#C87619"><b>● Building</b></span> · <span style="color:#CD4246"><b>● Failed</b></span> · <span style="color:#ABB3BF"><b>● Disabled</b></span></td>
</tr>
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Create deployment wizard</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Modal triggered by <span style="color:#2D72D2"><b>+ Create a deployment</b></span>. Fields: deployment name, description, source environment (Staging / Production), input dataset (batch only), output dataset path (batch only), replica count / CPU / GPU (live) or Spark profile (batch).</td>
</tr>
<tr style="background:#252A31">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Live deployment detail</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Tabs: <b>Overview</b> (endpoint URL, replica health), <b>Query</b> (interactive Single I/O or Multi I/O test console), <b>Deployment health</b> (service logs, Kubernetes host metrics, inference container metrics — 7-day retention), <b>Runtime configuration</b> (replica / CPU / GPU sliders).</td>
</tr>
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Batch deployment detail</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Shows input → output dataset lineage, current Spark profile, schedule status. Link navigates to the output dataset in Foundry's dataset explorer. <span style="color:#2D72D2"><b>Edit</b></span> button changes the Spark profile and triggers a rebuild.</td>
</tr>
<tr style="background:#252A31">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Function publishing</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Artifact sidebar <b>+</b> icon wraps a live deployment in a TypeScript Function, making it callable from Workshop widgets, Vertex, and Slate without touching the raw REST API.</td>
</tr>
</table>

The **Query tab** on a live deployment provides a live test console: choose Single I/O (tabular only) or Multi I/O, paste JSON matching the model's input schema, and see the JSON response inline — useful for smoke-testing immediately after a release upgrade.

---

## Worked example

**Scenario:** A fraud-detection model is trained weekly. The team wants real-time scoring for individual transactions (live) and nightly batch scoring of all pending transactions (batch).

1. A data scientist submits the new model to the `fraud-detection` Modeling Objective and creates a **Release** tagged `Production`, version `2.4.1`.
2. **Live deployment:** In the Deployments panel they click **+ Create a deployment**, name it `fraud-live-prod`, select `Production` environment, set 4 replicas / 2 CPU each. Foundry builds the container (~3 min). The endpoint URL is copied and handed to the application team; the Workshop app calls it via a published TypeScript Function. Next week when `2.5.0` is released to `Production`, the endpoint auto-upgrades — the app team does nothing.
3. **Batch deployment:** A second deployment is created named `fraud-batch-prod`, pointing at the `transactions_pending` input dataset and writing to `fraud_scores_nightly`. A logic schedule is added to rebuild `fraud_scores_nightly` on a nightly cron. When `2.5.0` releases, the transform logic updates and the next nightly build runs inference with the new model automatically.
4. The Deployment health tab shows Kubernetes metrics confirming the live endpoint is handling ~200 req/s with no errors. Batch run logs confirm 1.2 M rows scored in 18 min.

---

## Documentation map

- **Model Integration overview** — `/docs/foundry/model-integration/overview/`
- **Core concepts: Modeling Objectives** — `/docs/foundry/model-integration/objectives`
- **Set up a live deployment** — `/docs/foundry/manage-models/set-up-live`
- **Set up a batch deployment** — `/docs/foundry/manage-models/set-up-batch`
- **Create a direct model deployment** — `/docs/foundry/manage-models/create-a-model-deployment`
- **API: Query a live deployment (reference)** — `/docs/foundry/manage-models/live-deployment-reference`
- **Live deployment FAQ** — `/docs/foundry/manage-models/live-faq`
- **Live deployment compute usage** — `/docs/foundry/manage-models/compute-usage`
- **Tutorial: Productionize a model** — `/docs/foundry/model-integration/tutorial-productionize`

---

## Official documentation

- [Model Integration Overview](https://www.palantir.com/docs/foundry/model-integration/overview)
- [Core Concepts: Modeling Objectives](https://www.palantir.com/docs/foundry/model-integration/objectives)
- [Set up and use a Modeling Objective live deployment](https://www.palantir.com/docs/foundry/manage-models/set-up-live)
- [Set up a batch deployment](https://www.palantir.com/docs/foundry/manage-models/set-up-batch)
- [Create a direct model deployment](https://www.palantir.com/docs/foundry/manage-models/create-a-model-deployment)
- [API: Query a live deployment](https://www.palantir.com/docs/foundry/manage-models/live-deployment-reference)
- [Live deployment FAQ](https://www.palantir.com/docs/foundry/manage-models/live-faq)
- [Live deployment compute usage](https://www.palantir.com/docs/foundry/manage-models/compute-usage)
