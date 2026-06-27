# Model Studio

> Model Studio is Foundry's point-and-click interface for training machine-learning models with common algorithms — building model assets without writing training code.

## What it is

Model Studio lowers the barrier to building models. Instead of writing training scripts, you select input data, choose an algorithm, configure parameters, and train — all through a guided UI. The result is a **model asset** that can be submitted to a **Modeling Objective**, evaluated, and deployed. It's aimed at analysts and citizen data scientists who want predictive models without deep coding.

## When to use it

- You want to train standard ML models without writing code.
- You're an analyst/citizen data scientist building predictive models.
- You need a model asset to feed into a Modeling Objective and deployment.

**When NOT to use it / alternatives:** For custom architectures or advanced pipelines, train in **Code Repositories/Workspaces** and integrate via **model adapters**. For quick exploration, **Quiver** offers point-and-click ML too.

## Key concepts & terminology

- **Model Studio** — The no-code training application.
- **Algorithm** — The ML method chosen (e.g., classification, regression, tree-based).
- **Training configuration** — Inputs, target, features, and hyperparameters.
- **Model asset** — The trained artifact produced.
- **AutoML-style tooling** — Guided selection/tuning to simplify modeling.
- **Modeling Objective** — Where assets are submitted, evaluated, and released.

## Core capabilities / features

- **Point-and-click training** — Configure and train models via UI.
- **Common algorithms** — Standard classification/regression and related methods.
- **Feature/target selection** — Pick inputs and the prediction target visually.
- **Produces model assets** — Output integrates with Modeling Objectives.
- **Guided workflow** — Lower barrier for non-coders.

## How it works / typical workflow

1. **Open Model Studio** and select a training **dataset**.
2. **Choose the target** and **features**.
3. **Pick an algorithm** and set parameters.
4. **Train** the model and review preliminary metrics.
5. **Produce a model asset**.
6. **Submit** it to a **Modeling Objective** for evaluation, release, and deployment.

## Example

A demand-forecasting analyst selects `historical_sales`, sets `units_sold` as the target with seasonality features, picks a tree-based regressor, trains it in Model Studio, and submits the resulting asset to the "Demand Forecast" Modeling Objective for comparison against a colleague's model.

## How it connects to the rest of Foundry

- **Datasets** — Training data comes from Foundry datasets.
- **Modeling Objectives** — Receives and governs the produced model assets.
- **Deployments** — Released models are served live/batch.
- **Ontology** — Predictions integrate as object properties.
- **Code Workbook/Repos** — Alternatives for code-based model training.

## Tips & gotchas for learners

- **Great for standard models**, not exotic architectures — use code for those.
- **Clean features matter** — model quality depends on good input data.
- **Always evaluate** in a Modeling Objective before trusting a model.
- **It's a producer** — Model Studio makes assets; deployment/governance happen in Modeling Objectives.

## Official documentation

- [Model Studio: Overview](https://www.palantir.com/docs/foundry/model-studio/overview)
- [Modeling Objectives: Overview](https://www.palantir.com/docs/foundry/modeling-objectives/overview)
- [Model integration: Overview](https://www.palantir.com/docs/foundry/model-integration/overview)
