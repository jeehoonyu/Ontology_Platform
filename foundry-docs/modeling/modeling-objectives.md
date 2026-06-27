# Modeling Objectives

> Modeling Objectives are Foundry's "mission control" for machine-learning models — a structured place to submit, evaluate, review, release, and deploy models against a defined business objective.

## What it is

A Modeling Objective frames an ML problem ("predict equipment failure," "forecast demand") and provides the governance and lifecycle around solving it. Multiple model **submissions** can be compared against shared **evaluation** metrics, a chosen model can be **released**, and a release can be **deployed** (live or batch) for production use — often integrated into the Ontology so predictions become object properties. It brings rigor, review, and reproducibility to model operationalization.

## When to use it

- You're operationalizing an ML model for production use, not just experimenting.
- You need to compare candidate models against consistent metrics.
- You want governed release/deployment with review and versioning.
- You want model outputs available to the Ontology and apps.

**When NOT to use it / alternatives:** For quick, exploratory modeling use **Quiver** (point-and-click ML) or **Code Workbook**. Modeling Objectives is for the production lifecycle.

## Key concepts & terminology

- **Modeling Objective** — The container framing an ML problem and its lifecycle.
- **Submission** — A candidate model submitted to the objective.
- **Model asset** — The trained model artifact (from a notebook, repo, or Model Studio).
- **Evaluation** — Metrics/dashboards comparing submissions on test data.
- **Release** — A chosen, approved model version.
- **Deployment** — Serving a release: **live** (real-time) or **batch** (scheduled).
- **Model adapter** — Code wrapping a model so Foundry can run inference on it.

## Core capabilities / features

- **Submission & comparison** — Register multiple models and compare them side by side.
- **Standardized evaluation** — Automatic and custom metrics with dashboards.
- **Review & release** — Govern which model becomes the production version.
- **Live & batch deployment** — Serve in real time or run scheduled inference.
- **Ontology integration** — Surface predictions as object properties / function outputs.
- **Versioning & reproducibility** — Track model lineage and configuration.

## How it works / typical workflow

1. **Create a Modeling Objective** describing the problem and target.
2. **Train models** (Model Studio, Code Workbook, or a repo) to produce **model assets**.
3. **Submit** candidates to the objective.
4. **Evaluate** submissions against shared metrics.
5. **Review and release** the best model.
6. **Deploy** the release (live or batch) and integrate outputs into the Ontology.
7. **Monitor** performance and iterate.

## Example

Predicting churn: create a "Customer Churn" objective; train two models (logistic regression and gradient boosting); submit both; compare AUC/precision on the eval set; release the better one; deploy a **batch** inference that writes a `churnRisk` property onto each `Customer` object nightly, which a Workshop retention app then surfaces.

## How it connects to the rest of Foundry

- **Model Studio / Code Workbook / Repos** — Produce the model assets you submit.
- **Model adapters** — Make custom models runnable in Foundry.
- **Deployments** — Live/batch serving of released models.
- **Ontology / Functions** — Predictions become object properties and function outputs.
- **Observability** — Monitor inference metrics and health.

## Tips & gotchas for learners

- **Objective first, models second** — define the metric/target before comparing models.
- **Evaluate on consistent data** so comparisons are fair.
- **Release is a governance gate** — only approved models reach production.
- **Live vs batch** — choose based on latency needs (real-time scoring vs nightly).
- **Integrate with the Ontology** so predictions are usable by apps and Actions.

## Official documentation

- [Modeling Objectives: Overview](https://www.palantir.com/docs/foundry/modeling-objectives/overview)
- [Model integration: Overview](https://www.palantir.com/docs/foundry/model-integration/overview)
