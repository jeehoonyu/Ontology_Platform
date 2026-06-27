# Code Workbook

> Code Workbook is Foundry's interactive, graph-based analysis environment for rapidly building Python, R, and SQL transformations on a visual canvas.

## What it is

Code Workbook blends data engineering and data science. Instead of files in a repository, you work on a **canvas of nodes**, where each node is a snippet of Python, R, or SQL that transforms the output of upstream nodes. Results are computed interactively and cached, so you can iterate quickly — explore data, build features, prototype models — and then promote stable nodes into datasets. It sits between the no-code Contour and the full-code Code Repositories.

## When to use it

- Interactive, exploratory data science and feature engineering.
- You want Python/R/SQL flexibility but faster iteration than repositories.
- You're prototyping transformations or models before productionizing.

**When NOT to use it / alternatives:** For production, version-controlled pipelines use **Code Repositories** or **Pipeline Builder**. For pure point-and-click tabular analysis use **Contour**.

## Key concepts & terminology

- **Workbook** — The overall canvas/project.
- **Node** — A unit of code (Python/R/SQL) that produces an output.
- **Canvas / graph** — The visual layout of connected nodes.
- **Environment** — The managed set of libraries available to the workbook.
- **Spark / transform output** — Node results can be saved as Foundry datasets.
- **Template** — Reusable starter logic.

## Core capabilities / features

- **Multi-language** — Python, R, and SQL nodes in one workbook.
- **Visual graph of transformations** — See dependencies between code nodes.
- **Interactive execution & caching** — Run nodes individually; reuse cached outputs.
- **Managed environments** — Add libraries without manual environment management.
- **Save nodes as datasets** — Promote results into governed Foundry datasets.
- **Rich visualization** — Inspect dataframes and charts inline.
- **Collaboration** — Shareable, governed workbooks.

## How it works / typical workflow

1. **Create a Code Workbook** and select/configure its environment.
2. Add an **input node** pointing at a dataset.
3. Add **code nodes** (Python/R/SQL) that transform upstream outputs.
4. **Run nodes** interactively and inspect results/visualizations.
5. **Save** key nodes as output datasets.
6. Promote stable logic to **Code Repositories** or **Pipeline Builder** for production scheduling.

## Example

Exploring sales data: an input node loads `clean/sales`; a Python node computes monthly aggregates with pandas; an R node fits a quick trend model; a SQL node joins reference data. You inspect charts inline, then save the aggregates node as `analytics/monthly_sales`.

## How it connects to the rest of Foundry

- **Datasets** — Reads inputs and writes outputs as datasets.
- **Code Repositories / Pipeline Builder** — Where prototypes graduate for production.
- **Quiver / Contour** — Downstream analysis of the datasets you produce.
- **Modeling** — Prototype features/models before formalizing in Modeling Objectives.

## Tips & gotchas for learners

- **Great for prototyping, not production** — promote stable logic to a repository/pipeline with scheduling.
- **Cached outputs speed iteration** but can hide stale results — rerun when inputs change.
- **Mind environment size** — only add the libraries you need.
- **Save important nodes as datasets** so downstream tools can consume them.

## Official documentation

- [Code Workbook: Overview](https://www.palantir.com/docs/foundry/code-workbook/overview)
- [Analytics: Overview](https://www.palantir.com/docs/foundry/analytics/overview)
- [Dev toolchain: Overview](https://www.palantir.com/docs/foundry/dev-toolchain/overview)
