<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · MODELING</b><br>
<span style="font-size:22px"><b>Model Studio</b></span><br>
<span style="color:#ABB3BF">A no-code, point-and-click machine learning development environment for training and deploying production-grade models inside Foundry.</span>
</td></tr></table>

## What it is

Model Studio is Palantir Foundry's no-code ML development tool. It provides a visual, guided interface for configuring and launching model training jobs — covering time series forecasting, regression, and classification — without writing any code. Training jobs run as standard Foundry transforms, so all data lineage, access controls, and dataset markings apply automatically to outputs.

## How it works

Model Studio is built around three primary objects: **trainers**, **models**, and **experiments**. Understanding how these interact explains the full execution lifecycle.

**Core objects**

- **Trainer** — A bundled, production-grade training algorithm scoped to a specific ML task. Foundry ships three built-in trainers: *Time Series Forecasting*, *Regression*, and *Classification*. Each trainer exposes a set of task-specific configuration parameters with sensible defaults.
- **Model** — A versioned Foundry resource that holds the serialized artifact produced by a training run. Models provide a common interface used by all downstream consumers (Python transforms, Pipeline Builder, Functions, Modeling Objectives). Every time a training job completes, a new model version is written to the designated output path.
- **Experiment** — An artifact co-created alongside each model version that captures the full set of metrics, hyperparameters, and (for some trainers) visualization plots generated during training. Experiments live on the Model Studio home page and are linked to the model version that produced them.

**End-to-end execution flow**

1. **Create a Model Studio resource.** In a Foundry code folder, select **+ New > Model Studio**. This creates a versioned `.model-studio` resource in the repository.
2. **Select a trainer.** Choose one of the three built-in trainers. The UI updates to show task-specific fields.
3. **Provide datasets.** Map one or more Foundry datasets as the training input. Designate the target column. Optionally supply a separate test dataset; if omitted, Model Studio automatically reserves 20% of the training data for validation.
4. **Configure parameters.** Adjust trainer parameters (e.g., evaluation metric, training quality preset, time limit, prediction column name) or accept the defaults. Compute resources (vCPUs, memory) are also set here.
5. **Name the output model.** Specify the model resource name and destination folder within the repository.
6. **Launch the build.** Model Studio submits a standard Foundry transform job. The job reads the input datasets (respecting lineage and markings), trains the model, serializes the artifact, writes a versioned model resource, and creates an experiment record — all atomically.
7. **Monitor in real time.** While the job runs, training metrics stream into the Experiment viewer on the home page. A green indicator appears on completion; a red indicator flags failure.
8. **Downstream consumption.** The output model resource is immediately available for inference via Python transforms (`FoundryModel.from_rid(...)`), Pipeline Builder nodes, Foundry Functions, or submission to a Modeling Objective for production deployment gating.
9. **Automated retraining.** Build schedules can be attached to the Model Studio resource so that new training runs fire automatically when upstream datasets update, keeping the model current without manual intervention.

Because the training job is a Foundry transform, it participates in the platform's full provenance graph: every input dataset, configuration snapshot, and output model version is recorded, and any data markings (e.g., sensitivity labels) on input datasets propagate to the output model automatically.

## User interface

Model Studio lives inside a Foundry **code repository**. Once opened, the interface has two main areas: the **configuration panel** (left/center) and the **home page / experiment log** (right/center).

**Overall layout**

<table style="border-collapse:collapse;width:100%">
<tr style="background:#1C2127;color:#fff">
  <th style="padding:8px 12px;border:1px solid #383E47;text-align:left">Area</th>
  <th style="padding:8px 12px;border:1px solid #383E47;text-align:left">What lives here</th>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Home page</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">List of all training job runs with status chips and links to experiment records</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Trainer selector</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Dropdown or card-based picker for Forecasting / Regression / Classification</td>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Dataset mapper</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Search-and-select fields for training dataset, target column, and optional test dataset</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Parameters panel</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Trainer-specific knobs: quality preset, time limit, evaluation metric, prediction column name; inline docs shown per parameter</td>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Compute config</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">vCPU and memory sliders; usage measured in Foundry compute-seconds</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Experiment viewer</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Metric charts, parameter tables, and (trainer-dependent) visualization plots for a selected run</td>
</tr>
</table>

**Training run status chips**

<span style="color:#238551"><b>● success</b></span> — training completed and model version written
<span style="color:#C87619"><b>● running / pending</b></span> — job is queued or in progress
<span style="color:#CD4246"><b>● failed</b></span> — job errored; logs available in the experiment record
<span style="color:#2D72D2"><b>● launch build</b></span> — primary action button to submit a new training job

**Key interactions**

- Clicking a run row on the <span style="color:#8ABBFF">Home page</span> opens its <span style="color:#8ABBFF">Experiment viewer</span>, showing metrics and plots.
- The <span style="color:#2D72D2">**Submit to Modeling Objective**</span> button appears on the model version page after a successful run, enabling promotion to a production deployment pipeline.
- In-platform documentation for each parameter is shown inline in the <span style="color:#8ABBFF">Parameters panel</span> — no context-switching required.
- All configuration changes are versioned alongside the code repository, so the exact parameters that produced any model version are always recoverable.

## Worked example

**Task:** Predict California median house prices using a tabular regression model.

1. In a Foundry project's code folder, click **+ New > Model Studio** and name it `median_house_price_model_studio`.
2. In the Trainer selector, choose **Regression**. Set the output model name to `regression_model` in the `models/` folder.
3. In the Dataset mapper, select `housing_features_and_labels` as the training dataset and set the target column to `median_house_value`. Leave the test dataset field empty — Model Studio will hold out 20% automatically.
4. In the Parameters panel, set:
   - Evaluation metric: `root_mean_squared_error`
   - Training preset: `good_quality`
   - Time limit: `300` seconds
   - Prediction column: `prediction`
5. In Compute config, increase to **2 vCPUs / 8 GB memory** for sufficient capacity.
6. Click **Launch build**. The Home page shows a <span style="color:#C87619"><b>● running</b></span> chip; after ~5 minutes it flips to <span style="color:#238551"><b>● success</b></span>.
7. Click the run row to open the Experiment viewer; inspect RMSE curves and feature importance plots.
8. Navigate to the `regression_model` resource, open the latest version, and click **Submit to Modeling Objective** to promote it to the production evaluation pipeline.
9. Downstream Python transforms can now call `model.predict(df)` using the versioned model RID — no redeployment needed when a new version is submitted.

## Documentation map

The following sub-pages exist beneath Model Studio in the Palantir Foundry docs:

- **Model Studio / Overview** — entry point and feature summary
- **Model Studio / Core concepts** — trainers, models, experiments explained
- **Model Studio / Navigation** — UI walkthrough of the home page and configuration screens
- **Model Studio / Model trainers / Time series forecasting** — forecasting trainer reference
- **Model Studio / Model trainers / Regression** — regression trainer reference
- **Model Studio / Model trainers / Classification** — classification trainer reference
- **Model Studio / Configuration / Inputs** — dataset mapping configuration
- **Model Studio / Configuration / Compute resources** — vCPU / memory settings
- **Model Studio / Troubleshooting** — common errors and remediation
- **Model Studio / FAQs** — frequently asked questions
- **Model integration / Core concepts / Selecting the right modeling tool** — Model Studio vs Code Workspaces vs Code Repositories
- **Model integration / Core concepts / Models** — the Model resource type in depth
- **Tutorial: Supervised machine learning / Set up a project** — project scaffolding walkthrough
- **Tutorial: Supervised machine learning / Train a model in Model Studio** — end-to-end regression tutorial

## Official documentation

- [Model Studio — Overview](https://www.palantir.com/docs/foundry/model-studio/overview)
- [Model Studio — Core concepts](https://www.palantir.com/docs/foundry/model-studio/core-concepts)
- [Model Studio — Classification trainer](https://www.palantir.com/docs/foundry/model-studio/trainers-classification)
- [Model Studio — Regression trainer](https://www.palantir.com/docs/foundry/model-studio/trainers-regression)
- [Model Studio — Time series forecasting trainer](https://www.palantir.com/docs/foundry/model-studio/trainers-timeseries-forecasting)
- [Model Studio — Compute resources configuration](https://www.palantir.com/docs/foundry/model-studio/configuration-compute-resources)
- [Model integration — Core concepts: Model Studio](https://www.palantir.com/docs/foundry/model-integration/model-studio)
- [Model integration — Selecting the right modeling tool](https://www.palantir.com/docs/foundry/model-integration/what-to-use)
- [Tutorial: Train a model in Model Studio](https://www.palantir.com/docs/foundry/model-integration/tutorial-train-model-studio)
- [Tutorial: Set up a machine learning project in Foundry](https://www.palantir.com/docs/foundry/model-integration/tutorial-set-up-project)
