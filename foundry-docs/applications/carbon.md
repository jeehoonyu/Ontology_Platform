# Carbon

> Carbon is Foundry's unified workspace that brings multiple applications and modules together into one navigable, branded experience for end users.

## What it is

Operational users often need several Foundry apps (Workshop modules, Object Explorer, Map, reports) as part of one job. Carbon stitches these into a single coherent workspace with shared navigation, so users move between tools without hopping across disconnected URLs. It's the "shell" or portal layer that organizes a collection of capabilities into one product experience.

## When to use it

- You're delivering a suite of related apps/modules as one product.
- End users need unified navigation across Workshop modules and other Foundry tools.
- You want a branded, organized landing experience rather than scattered links.

**When NOT to use it / alternatives:** For a single app, a standalone **Workshop** module is enough. For fully custom portals, an **OSDK** app gives total control.

## Key concepts & terminology

- **Carbon workspace** — The unified container/portal.
- **Module / app** — Individual Workshop apps or Foundry tools surfaced within Carbon.
- **Navigation** — The shared menu/structure tying modules together.
- **Home / landing** — The entry experience users see first.
- **Collection** — A grouped set of apps/resources presented together.

## Core capabilities / features

- **Unified navigation** — One shell across many apps/modules.
- **Workspace organization** — Group and structure related capabilities.
- **Branded experience** — A coherent, polished entry point for end users.
- **Integrates Foundry tools** — Surface Workshop modules and other applications together.
- **Governed access** — Respects each underlying resource's permissions.

## How it works / typical workflow

1. **Create a Carbon workspace.**
2. **Add modules/apps** (Workshop modules and other Foundry tools).
3. **Configure navigation** and the home/landing experience.
4. **Brand and organize** the workspace.
5. **Share** the workspace with the intended user group.

## Example

A "Field Operations" workspace bundles a Workshop dispatch app, a Map view of assets, an Object Explorer for incidents, and a Notepad shift-report — all under one Carbon navigation menu, so field supervisors do their whole job from a single, branded portal.

## How it connects to the rest of Foundry

- **Workshop** — Carbon's primary content is usually Workshop modules.
- **Map / Object Explorer / Notepad** — Additional tools surfaced in the workspace.
- **Security** — Each module inside Carbon keeps its own governance.
- **Marketplace / DevOps** — Carbon workspaces can be packaged as part of products.

## Tips & gotchas for learners

- **Carbon is the shell, not the app** — build the apps in Workshop, then assemble in Carbon.
- **Use it when delivering a suite** — single apps don't need it.
- **Navigation design matters** — organize around the user's job, not the tools.
- **Permissions still apply** per underlying module.

## Official documentation

- [Carbon: Modules overview](https://www.palantir.com/docs/foundry/carbon/modules-overview)
- [Workshop: Overview](https://www.palantir.com/docs/foundry/workshop/overview)
