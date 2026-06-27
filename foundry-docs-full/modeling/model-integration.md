<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · MODELING</b><br>
<span style="font-size:22px"><b>Model Integration &amp; Adapters</b></span><br>
<span style="color:#ABB3BF">A unified framework for registering, governing, and deploying any ML model—whether trained inside Foundry or imported from external sources—via a typed adapter contract.</span>
</td></tr></table>

## What it is

Model Integration is Palantir Foundry's end-to-end system for treating machine learning models as first-class platform artifacts. A **Model** in Foundry consists of two inseparable parts: (1) **model artifacts** (the serialized weights, checkpoints, or container image) and (2) a **Model Adapter** (a Python class that tells Foundry how to load those artifacts and run inference on them). Once registered, a model inherits the full platform stack—lineage, versioning, permissioning, and auditing—and can be consumed in batch pipelines, live REST deployments, Ontology Functions, and application layers without rebuilding integrations for each target.

---

## How it works

### 1. Author a Model Adapter

A Model Adapter is a Python class that extends `ModelAdapter` from the `palantir_models` package. Four core methods drive the contract:

| Method | When called | Purpose |
|--------|-------------|---------|
| `api(cls)` | At registration & runtime type-check | Declares typed input/output schema |
| `load()` | On model initialization | Deserializes artifacts from storage |
| `predict(...)` | On each inference call | Runs the actual ML logic |
| `init_container()` / `init_external()` | For Docker or API-hosted models | Bootstraps a remote or containerized runtime |

The `api()` classmethod returns two dicts—`inputs` and `outputs`—using types from `palantir_models` (`pm`):

```python
from palantir_models import ModelAdapter
import palantir_models as pm

class SklearnRegressionAdapter(ModelAdapter):

    @classmethod
    def api(cls):
        inputs  = {"df": pm.Pandas(columns=[("sq_ft", float), ("rooms", int)])}
        outputs = {"df": pm.Pandas(columns=[("sq_ft", float), ("rooms", int),
                                            ("price_pred", float)])}
        return inputs, outputs

    def load(self, storage):
        import joblib
        self.model = joblib.load(storage.get_model())

    def predict(self, df):
        df["price_pred"] = self.model.predict(df[["sq_ft","rooms"]])
        return df
```

Supported `pm` types include: `pm.Pandas`, `pm.Spark`, `pm.Parameter`, `pm.FileSystem`, `pm.MediaReference`, `pm.Object`, `pm.ObjectSet`, and `pm.NDArray`. Column types are strictly enforced at runtime.

### 2. Publish the adapter as a library

The adapter class lives in a **Code Repository** or **Jupyter workspace** and is published as a versioned Python library to Foundry's internal package registry. The `@auto_serialize` annotation handles standard serialization automatically. For dependency isolation (e.g., conflicting CUDA versions), setting `use_sidecar = True` runs the model inside its own container sidecar.

### 3. Train and save artifacts

Training code writes the artifact (e.g., a `joblib` file, a PyTorch `.pt` checkpoint, or an ONNX model) to a **Model** resource. The Model resource acts as a versioned artifact store—each save creates an immutable snapshot with a new version number. Training can happen in Foundry's Code Repositories, Jupyter notebooks, or Model Studio, or artifacts can be uploaded manually or pulled from an external container registry.

### 4. Register the model under a Modeling Objective

A **Modeling Objective** is the governance hub for a single operational problem (e.g., "Predict housing prices"). Submitting a trained model to an objective creates an immutable **submission**, analogous to a pull request, and initiates the review/evaluation workflow. Submissions are evaluated against a **MetricSet**—a bundle of numerical metrics, images, and charts—computed over a designated evaluation dataset. All submissions are ranked and compared side-by-side.

### 5. Release

An approved submission is packaged into a **Release**: a versioned, production-ready asset tagged with environment labels (e.g., `Staging`, `Production`) and release notes. Releases protect downstream consumers—deployments point to a release tag and upgrade intentionally, never automatically from a raw commit.

### 6. Deploy

Foundry supports two deployment modes from a release:

- **Batch Deployment** — The model runs inside a Pipeline Builder transform. You specify an input dataset, an output dataset, and a rebuild schedule. Distributed Spark compute handles scale. Each rebuild is recorded in lineage.
- **Live Deployment** — Foundry provisions a serverless REST endpoint. Low-latency queries arrive as HTTP calls; the endpoint maintains high availability and supports independent permissioning. This is the backend for Functions on Models and for external application integrations.

### 7. Feedback and iteration

Foundry captures production outcomes (user actions, ground-truth labels fed back via pipelines) and surfaces them in the Modeling Objective, closing the loop for continuous model improvement.

---

## User interface

The Model Integration UI is spread across three linked surfaces inside Foundry:

**Modeling Objective workspace** — The primary screen. Opened from the Foundry home or from search, it presents a left-side navigation tree with sections for <span style="color:#8ABBFF">**Submissions**</span>, <span style="color:#8ABBFF">**Releases**</span>, <span style="color:#8ABBFF">**Deployments**</span>, <span style="color:#8ABBFF">**Metrics**</span>, and <span style="color:#8ABBFF">**Data Sources**</span>. The main panel renders the selected section in a card-based layout on a <span style="color:#1C2127">dark panel</span> background. A top toolbar provides submission and release action buttons.

**Model resource page** — Accessed by navigating to the Model artifact directly. Shows version history, artifact metadata, the linked adapter library version, and a preview of the `api()` schema (input/output column types rendered as a typed table).

**Code Repository / Jupyter workspace** — Where the adapter class is authored. The editor surfaces linting from the `palantir_models` type system. The "Publish" button snapshots the library to the package registry, making it available for linking to a Model resource.

<table style="border-collapse:collapse;width:100%">
<tr style="background:#1C2127">
<th style="padding:8px 12px;color:#ABB3BF;border:1px solid #383E47;text-align:left">UI element</th>
<th style="padding:8px 12px;color:#ABB3BF;border:1px solid #383E47;text-align:left">Where it lives</th>
<th style="padding:8px 12px;color:#ABB3BF;border:1px solid #383E47;text-align:left">Status indicators</th>
</tr>
<tr style="background:#252A31">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Submission card</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Modeling Objective → Submissions</td>
<td style="padding:8px 12px;border:1px solid #383E47">
<span style="color:#238551"><b>● Approved</b></span> ·
<span style="color:#C87619"><b>● In Review</b></span> ·
<span style="color:#CD4246"><b>● Rejected</b></span>
</td>
</tr>
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Release tag</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Modeling Objective → Releases</td>
<td style="padding:8px 12px;border:1px solid #383E47">
<span style="color:#238551"><b>● Production</b></span> ·
<span style="color:#C87619"><b>● Staging</b></span>
</td>
</tr>
<tr style="background:#252A31">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Batch deployment</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Modeling Objective → Deployments</td>
<td style="padding:8px 12px;border:1px solid #383E47">
<span style="color:#238551"><b>● Running</b></span> ·
<span style="color:#C87619"><b>● Building</b></span> ·
<span style="color:#CD4246"><b>● Failed</b></span>
</td>
</tr>
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Live deployment</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Modeling Objective → Deployments</td>
<td style="padding:8px 12px;border:1px solid #383E47">
<span style="color:#238551"><b>● Active</b></span> ·
<span style="color:#CD4246"><b>● Disabled</b></span>
</td>
</tr>
<tr style="background:#252A31">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>MetricSet panel</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Modeling Objective → Metrics</td>
<td style="padding:8px 12px;border:1px solid #383E47">Charts, numeric scores, images rendered inline</td>
</tr>
</table>

Key interactions: clicking <span style="color:#2D72D2">**Submit model**</span> opens a modal to select a Model resource version and attach metadata. Clicking <span style="color:#2D72D2">**Create release**</span> from an approved submission prompts for a version tag and environment label. Clicking <span style="color:#2D72D2">**Create deployment**</span> from a release presents a wizard to choose batch vs. live mode and configure I/O datasets or endpoint settings.

---

## Worked example

**Scenario:** A data science team builds a scikit-learn housing price regressor and wants to serve predictions in a Foundry application.

1. **Author adapter** — In a Code Repository, the team writes `HousingAdapter(ModelAdapter)` with `api()` declaring `sq_ft: float` and `rooms: int` as inputs and `price_pred: float` as output. They publish the library.
2. **Train and save** — A Jupyter notebook trains the model on the `housing_train` dataset, saves the `joblib` artifact to a Model resource (`Housing Price Model v1`), and links the published adapter library to it.
3. **Submit to objective** — The team navigates to the `Housing Price Prediction` Modeling Objective and clicks **Submit model**, selecting `v1`. The submission card appears with status <span style="color:#C87619"><b>● In Review</b></span>.
4. **Evaluate** — The Objective auto-runs the MetricSet (RMSE, R²) against `housing_eval` dataset. Results populate the Metrics panel. A reviewer approves the submission; status flips to <span style="color:#238551"><b>● Approved</b></span>.
5. **Release** — The team creates release `v1.0.0` tagged `Production`.
6. **Deploy batch** — A batch deployment is configured pointing `housing_inference_data` → `housing_predictions`. The Pipeline Builder transform runs on schedule; results land in `housing_predictions` with full lineage.
7. **Deploy live** — A live deployment is enabled for the application. The app calls the REST endpoint; `HousingAdapter.predict()` runs server-side and returns `price_pred` in milliseconds.
8. **Iterate** — Six months later, `v2` is submitted with an XGBoost model. The objective's submission comparison view shows RMSE improved by 8%. The release tag is bumped to `v2.0.0`; the batch deployment adopts the new release; the live endpoint hot-swaps with zero downtime.

---

## Documentation map

The following sub-pages exist beneath Model Integration in the Palantir Foundry docs:

- **Overview** — `model-integration/overview` — Platform approach, model sources, integration philosophy
- **Core concepts: Models** — `model-integration/models` — Artifact + adapter two-component structure
- **Core concepts: Modeling Objectives** — `model-integration/objectives` — Submissions, releases, deployments, metrics
- **Core concepts: Modeling Experiments** — `model-integration/experiments` — Experiment tracking during training
- **Core concepts: Functions on Models** — `model-integration/functions-on-models` — Ontology-layer model invocation
- **Core concepts: Model Studio** — `model-integration/model-studio` — No-code AutoML training UI
- **Core concepts: Selecting the right tool** — `model-integration/what-to-use` — Decision guide across training environments
- **Model Adapter: Overview** — `integrate-models/model-adapter-overview` — Generalized framework, all model source types
- **Model Adapter: API definition** — `integrate-models/model-adapter-api` — `api()`, `predict()`, `load()` full reference
- **Model Adapter: API reference** — `integrate-models/model-adapter-reference` — Full `ModelAdapter` class reference
- **Model Adapter: Language model adapters** — `integrate-models/language-models-adapters` — LLM-specific adapter patterns
- **Model Adapter: Upgrade without retraining** — `integrate-models/upgrade-model-adapter` — Swap adapter code independently of weights
- **Model Adapter: `ModelInput` in transforms** — `integrate-models/transform-model-input` — Using models inside Pipeline Builder
- **Tutorial: Train in Code Repositories** — `model-integration/tutorial-train-code-repositories`
- **Tutorial: Train in Jupyter notebooks** — `model-integration/tutorial-train-jupyter-notebook`
- **Tutorial: Productionize a model** — `model-integration/tutorial-productionize`

---

## Official documentation

- [Overview · Model Integration · Palantir](https://www.palantir.com/docs/foundry/model-integration/overview)
- [Core concepts · Models · Palantir](https://www.palantir.com/docs/foundry/model-integration/models)
- [Core concepts · Modeling Objectives · Palantir](https://www.palantir.com/docs/foundry/model-integration/objectives)
- [Tutorial: Productionize a model · Palantir](https://www.palantir.com/docs/foundry/model-integration/tutorial-productionize)
- [Model Adapters · Overview · Palantir](https://www.palantir.com/docs/foundry/integrate-models/model-adapter-overview/index.html)
- [Model Adapter · API definition · Palantir](https://www.palantir.com/docs/foundry/integrate-models/model-adapter-api)
- [Model Adapter · API Reference · Palantir](https://www.palantir.com/docs/foundry/integrate-models/model-adapter-reference)
