# Workshop

> Workshop is Foundry's flagship no-code/low-code application builder for creating interactive, production-grade operational applications on top of the Ontology.

## What it is

Workshop is how you turn the Ontology into apps that operational users actually use day to day — inbox/triage tools, common operating pictures, review queues, dispatch consoles. Builders assemble applications from a library of **widgets**, bind them to **variables** and **object sets**, lay them out with **layouts**, and wire interactivity with **events**. Writeback happens through Ontology **Actions** and business logic through **Functions**, so apps are governed and consistent without managing front-end infrastructure.

## When to use it

- Building interactive operational apps for non-technical users.
- You need writeback (users editing objects) via governed Actions.
- You want a polished, consistent UI without writing/deploying React code.
- Common patterns: alert inboxes, task management, common operating pictures (COPs).

**When NOT to use it / alternatives:** For highly custom UIs use **Slate** or an **OSDK** React app; for pure analysis use **Contour/Quiver**; for documents use **Notepad**.

## Key concepts & terminology

- **Module** — A single Workshop application (a page/app).
- **Widget** — A UI component (object table, button, form, chart, map, filter, etc.).
- **Variable** — App state (selected objects, filter values, toggles) that widgets read/write.
- **Object set** — A collection of Ontology objects bound to widgets.
- **Layout** — How widgets are arranged (sections, tabs, panels, responsive layouts).
- **Event** — A triggered behavior (on click, on change) that updates variables or runs Actions.
- **Action** — Governed Ontology writeback invoked from the app.
- **Function** — Custom logic (TypeScript/Python) backing widgets or computed values.

## Core capabilities / features

- **Rich widget library** — Object tables, lists, forms, charts, maps, filters, buttons, KPI cards, and more.
- **Variables & reactivity** — App state drives a reactive UI; widgets respond to variable changes.
- **Events system** — Compose interactivity: clicks/changes trigger Actions, navigation, and state updates.
- **Layouts** — Sophisticated, responsive arrangements including tabs, sections, and mobile support.
- **Actions for writeback** — Users create/edit/delete objects through governed Action types.
- **Functions integration** — Back widgets and computed values with custom logic.
- **AIP integration** — Embed AIP Logic/agents for AI-assisted workflows.
- **Consistent design system** — Cohesive look and quality UX out of the box.

## How it works / typical workflow

1. **Create a module** and define **variables** (e.g., a selected object set).
2. **Add widgets** (object table, detail view, buttons) and bind them to variables/object sets.
3. **Arrange a layout** with sections/tabs for the workflow.
4. **Wire events** — clicking a row sets the selected object; a button runs an **Action**.
5. **Add Functions** for computed values or custom logic.
6. **Preview, test, and publish**; manage versions and access.

## Example

An incident-triage app: an **object table** lists open `Incident` objects; selecting a row sets a `selectedIncident` **variable**; a detail panel shows its properties; an "Assign to me" **button** runs an Action updating the owner; a filter widget narrows by severity. Operators clear their queue without ever touching raw datasets.

## How it connects to the rest of Foundry

- **Ontology** — Workshop is built on object types, object sets, links, Actions, and Functions.
- **Actions** — Provide all governed writeback in the app.
- **Functions / AIP Logic** — Back custom logic and AI workflows.
- **Object Explorer** — Saved object sets feed Workshop modules.
- **Map / charts** — Embeddable widgets for geospatial and analytical views.
- **Carbon** — Ties multiple Workshop modules into a unified workspace.

## Tips & gotchas for learners

- **Variables are the heart** — most interactivity flows through reading/writing variables.
- **Writeback = Actions** — you can't edit objects without an Action type.
- **Design the object model first** — a clean Ontology makes Workshop apps simple.
- **Events compose** — complex behavior is many small event steps; build incrementally.
- **Preview often** — test interactions as you wire them.
- **Performance** — large object tables/filters need thoughtful object-set design.

## Official documentation

- [Workshop: Overview](https://www.palantir.com/docs/foundry/workshop/overview)
- [Ontology: Overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Action types: Overview](https://www.palantir.com/docs/foundry/action-types/overview)
