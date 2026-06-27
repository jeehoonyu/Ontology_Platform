# Fusion (Spreadsheets)

> Fusion is Foundry's spreadsheet application that combines familiar spreadsheet computation with live access to the Ontology and Foundry's object-driven query system.

## What it is

Fusion brings the spreadsheet — the most widely understood analytics tool — into Foundry, but wired to governed data. Instead of pasting stale exports into Excel, analysts work in a spreadsheet whose cells can reference live Ontology objects, datasets, and queries. Formulas compute as usual, but the inputs stay connected to Foundry, so analyses are reproducible and governed rather than one-off files on someone's laptop.

## When to use it

- Spreadsheet-style modeling and calculation on governed Foundry data.
- Analysts who prefer formulas and grids over code or BI tools.
- Lightweight reporting that needs to stay connected to live data.

**When NOT to use it / alternatives:** For large-scale tabular transforms use **Contour**; for operational apps use **Workshop**; for code-driven analysis use **Code Workbook**.

## Key concepts & terminology

- **Workbook / sheet** — The spreadsheet document and its tabs.
- **Cell / formula** — Standard spreadsheet computation.
- **Object reference** — A cell/range backed by live Ontology objects.
- **Query** — An object-driven data pull feeding cells.
- **Reference data** — Connected Foundry datasets/objects, not static pastes.

## Core capabilities / features

- **Familiar spreadsheet UX** — Cells, formulas, and grids analysts already know.
- **Live Ontology integration** — Reference objects and object sets directly.
- **Object-driven queries** — Pull governed data into the sheet dynamically.
- **Reproducible & governed** — Inputs stay connected and permissioned, not exported.
- **Computation + Foundry data** — Combine ad-hoc math with platform data products.

## How it works / typical workflow

1. **Create a Fusion workbook** in a project.
2. **Reference Foundry data** — bring in object sets or query results.
3. **Write formulas** that compute over those references.
4. **Build a model/report** as you would in a spreadsheet.
5. **Refresh** to recompute against live data.
6. **Share** the governed workbook with stakeholders.

## Example

A finance analyst builds a budget-vs-actuals model: pull the `CostCenter` object set and actual spend into a Fusion sheet, write variance formulas against budget figures, and share a workbook that refreshes against live data each month — replacing a fragile, manually-updated Excel file.

## How it connects to the rest of Foundry

- **Ontology** — Cells reference live objects and object sets.
- **Datasets** — Reference data comes from governed Foundry data.
- **Workshop / Notepad** — Complementary surfaces for apps and reports.
- **Security** — Spreadsheet data inherits Foundry permissions/markings.

## Tips & gotchas for learners

- **References stay live** — that's the whole point versus exporting to Excel.
- **Governed, not local** — data access follows Foundry permissions.
- **Great for finance/ops modeling** that must stay connected to source data.
- **Not a heavy-transform tool** — for big reshaping, use Contour or transforms.

## Official documentation

- [Fusion: Overview](https://www.palantir.com/docs/foundry/fusion/overview)
- [Analytics: Overview](https://www.palantir.com/docs/foundry/analytics/overview)
