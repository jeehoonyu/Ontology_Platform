# Code Workspaces (VS Code / Jupyter)

> Code Workspaces give you a hosted, familiar IDE — VS Code or JupyterLab — running on Foundry compute with direct access to platform data, the Ontology, and the OSDK.

## What it is

Some development is better in a real IDE than a browser editor. Code Workspaces provision a managed development environment (VS Code Workspaces or Jupyter/JupyterLab) that runs in Foundry, so you get the tools you know — extensions, notebooks, terminals — while staying inside the platform's data access and governance. They're used for interactive data science, building OSDK-powered React applications, and developing where a full IDE is helpful.

## When to use it

- You want a full IDE (VS Code) or notebook environment (Jupyter) over Foundry data.
- You're building an **OSDK** React/TypeScript application interactively.
- You're doing exploratory data science with notebooks and need platform access.

**When NOT to use it / alternatives:** For production, reviewed pipeline code use **Code Repositories**. For purely point-and-click analysis use **Code Workbook** or **Contour**.

## Key concepts & terminology

- **Code Workspace** — A hosted dev environment (VS Code or Jupyter) on Foundry compute.
- **VS Code Workspace** — Browser-hosted VS Code integrated with Developer Console for app building.
- **JupyterLab Workspace** — Notebook-based interactive environment.
- **Developer Console** — The hub for building OSDK applications, OAuth clients, and SDKs.
- **Global branching** — Branch-aware development across resources for a safe workflow.
- **OSDK** — The generated Ontology SDK these workspaces commonly consume.

## Core capabilities / features

- **Familiar IDEs** — Real VS Code or JupyterLab, with extensions and terminals.
- **Hosted compute** — Runs in Foundry; no local environment setup.
- **Direct data & Ontology access** — Read datasets and call the Ontology/OSDK from your code.
- **App development** — Rapidly build React apps wired to the Ontology via OSDK and Developer Console.
- **Notebooks** — Interactive Python data science with rich output.
- **Governed** — Inherits Foundry permissions and markings.

## How it works / typical workflow

1. **Create a Code Workspace** (VS Code or Jupyter) in a project.
2. The environment provisions on Foundry compute.
3. **Access data** — read datasets, generate/consume an **OSDK**, call platform APIs.
4. For apps, use **Developer Console** to register an OAuth client and scaffold a React app.
5. Develop interactively; commit code as appropriate.
6. Promote to production via Code Repositories / DevOps where needed.

## Example

You're building a customer-facing React dashboard on the Ontology: open a **VS Code Workspace**, generate the **OSDK** from your ontology, scaffold a React app via **Developer Console**, and iterate live — querying `Order` and `Customer` objects through the typed SDK — all hosted in Foundry.

## How it connects to the rest of Foundry

- **Ontology SDK (OSDK)** — Workspaces are a primary place to build OSDK apps.
- **Developer Console** — Manages OAuth clients, SDK generation, and app deployment.
- **Code Repositories** — Complementary; repos for production pipelines, workspaces for IDE/interactive work.
- **Datasets / Platform APIs** — Accessible from workspace code.

## Tips & gotchas for learners

- **Workspaces are for interactive/IDE work**; production pipelines belong in repositories.
- **OSDK + Developer Console** is the standard path for custom apps.
- **Environments are governed** — data access follows your Foundry permissions.
- **Persist important code** in a repository; treat workspace scratch space as ephemeral.

## Official documentation

- [Code Workspaces: Overview](https://www.palantir.com/docs/foundry/code-workspaces/overview)
- [Ontology SDK: Overview](https://www.palantir.com/docs/foundry/ontology-sdk/overview)
- [Dev toolchain: Overview](https://www.palantir.com/docs/foundry/dev-toolchain/overview)
