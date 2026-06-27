# Model Integration & Adapters

> Model integration is how any model — trained in Foundry, in a notebook, in a container, or hosted externally — is brought into the platform so it can be evaluated, deployed, and used; model adapters are the glue code that makes a model runnable.

## What it is

Foundry doesn't care where a model came from — it cares that it can run inference on it consistently. **Model integration** covers all the ways models enter the platform: **model assets** trained in Foundry, **container models** packaged with their own runtime, and **externally hosted models** (e.g., SageMaker, Vertex AI). A **model adapter** is a thin wrapper you write that tells Foundry how to load the model and run predictions, giving every model a uniform interface for evaluation and deployment.

## When to use it

- You trained a model outside Model Studio (notebook, repo, custom framework).
- You need to integrate a model with unusual dependencies (container model).
- You want to use a model hosted on an external service from within Foundry.

**When NOT to use it / alternatives:** For standard in-platform training, **Model Studio** produces assets directly. For LLMs specifically, see the **AIP Model Catalog / BYOM**.

## Key concepts & terminology

- **Model asset** — A trained model artifact stored in Foundry.
- **Model adapter** — Code wrapping the model's load/predict interface for Foundry.
- **Container model** — A model packaged in a Docker container with its own runtime.
- **Externally hosted model** — A model served elsewhere (SageMaker/Vertex) and called from Foundry.
- **Inference** — Running the model to produce predictions.
- **Model version** — A tracked iteration of a model.

## Core capabilities / features

- **Multiple integration paths** — In-platform assets, containers, and external hosts.
- **Model adapters** — Uniform load/predict interface across model types.
- **Container models** — Bring complex/unusual dependencies via Docker.
- **External model connectivity** — Call models hosted on cloud ML services.
- **Versioning & lineage** — Track model iterations and their data.
- **Feeds Modeling Objectives & deployments** — Integrated models flow into the lifecycle.

## How it works / typical workflow

1. **Train or obtain a model** (notebook, repo, external service, or container).
2. **Write a model adapter** describing how to load it and run inference.
3. **Register it** as a model asset / integrated model in Foundry.
4. **Submit to a Modeling Objective** for evaluation.
5. **Deploy** (live or batch) once released.
6. **Use predictions** in the Ontology, Functions, and apps.

## Example

A team trains a PyTorch model in a Code Workspace with custom preprocessing. They package it as a **container model**, write a **model adapter** exposing a `predict()` method, register it, evaluate it in a Modeling Objective, and deploy a live endpoint that a Function calls to score incoming `Application` objects.

## How it connects to the rest of Foundry

- **Modeling Objectives** — Integrated models are evaluated and released there.
- **Deployments** — Serve integrated models live or batch.
- **Compute Modules** — Related mechanism for containerized serving.
- **Ontology / Functions** — Consume model predictions.
- **AIP Model Catalog / BYOM** — The LLM-specific counterpart to model integration.

## Tips & gotchas for learners

- **The adapter is the contract** — get load/predict right and the rest of the lifecycle just works.
- **Container models** are for awkward dependencies; simple models don't need them.
- **External models** keep serving elsewhere but are governed/called through Foundry.
- **Version everything** — reproducibility depends on tracking model + data versions.

## Official documentation

- [Model integration: Overview](https://www.palantir.com/docs/foundry/model-integration/overview)
- [Modeling Objectives: Overview](https://www.palantir.com/docs/foundry/modeling-objectives/overview)
