# Slate

> Slate is Foundry's low-code application builder for creating highly-customized, data-driven web applications using widgets, queries, and JavaScript — when you need more control than Workshop offers.

## What it is

Slate sits between Workshop's structured, Ontology-first app building and fully custom OSDK React development. It gives builders a canvas of **widgets** wired together with **queries** (to datasets, the Ontology, and APIs) and **JavaScript functions**, plus direct HTML/CSS control. That flexibility makes Slate powerful for bespoke dashboards and tools with custom interactions, at the cost of more hands-on building than Workshop.

## When to use it

- You need custom UI/behavior beyond Workshop's widget model.
- You want to wire queries to datasets/APIs with custom JavaScript logic.
- You're building a tailored dashboard or tool and are comfortable with light coding.

**When NOT to use it / alternatives:** For Ontology-centric operational apps prefer **Workshop** (faster, more governed). For full custom front-ends use an **OSDK React app**. For analysis use **Contour/Quiver**.

## Key concepts & terminology

- **Application** — The Slate app you build.
- **Widget** — A UI element (table, chart, input, button, HTML block, etc.).
- **Query** — A data request to a dataset, the Ontology, or an API, feeding widgets.
- **Function (JS)** — Custom JavaScript logic transforming data or handling events.
- **Variable / state** — Values widgets and queries read and write.
- **HTML/CSS** — Direct markup/styling control for custom presentation.

## Core capabilities / features

- **Widget-based building** — Compose UIs from a library of widgets.
- **Queries** — Pull from datasets, Ontology, and external/REST APIs.
- **JavaScript functions** — Custom logic for transformations and interactivity.
- **HTML/CSS control** — Fine-grained presentation customization.
- **Eventing & variables** — Reactive state drives the app.
- **Embeds & integration** — Combine with other Foundry artifacts.

## How it works / typical workflow

1. **Create a Slate application.**
2. **Define queries** to the data you need (datasets/Ontology/APIs).
3. **Add widgets** and bind them to query results/variables.
4. **Write JS functions** for custom logic and event handling.
5. **Style with HTML/CSS** as needed.
6. **Test and publish** the application.

## Example

A custom monitoring dashboard: queries pull live metrics from a dataset and statuses from the Ontology; JavaScript functions compute derived indicators; custom-styled HTML widgets present a branded layout with conditional coloring — more bespoke than a standard Workshop layout would allow.

## How it connects to the rest of Foundry

- **Datasets / Ontology / APIs** — Slate queries pull from all three.
- **Workshop** — The more structured, Ontology-first alternative.
- **Functions** — Server-side Ontology logic complements Slate's client-side JS.
- **OSDK apps** — The next step up in customization.

## Tips & gotchas for learners

- **Power vs. speed** — Slate is more flexible but slower to build than Workshop.
- **Prefer Workshop for Ontology writeback** workflows unless you need Slate's customization.
- **Mind maintainability** — custom JS/HTML needs upkeep as requirements change.
- **Queries drive everything** — design them before wiring widgets.

## Official documentation

- [Slate: Overview](https://www.palantir.com/docs/foundry/slate/overview)
- [Workshop: Overview](https://www.palantir.com/docs/foundry/workshop/overview)
