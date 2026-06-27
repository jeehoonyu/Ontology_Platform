# Marketplace

> Marketplace is Foundry's storefront for discovering, installing, and automatically upgrading packaged data products — turning solutions built with Foundry DevOps into reusable, distributable packages.

## What it is

Once a team packages a solution as a **product** (via Foundry DevOps), Marketplace is where others find and install it. It provides discoverability (a browsable store), guided installation workflows that wire up the product's resources in the target project, and automated upgrade management with maintenance windows and release channels. Marketplace is how reusable solutions — pipelines, ontologies, apps — spread across an organization or between Foundry environments without manual rebuilding.

## When to use it

- You want to install a pre-built product (internal or vendor) into your environment.
- You've packaged a solution and want others to discover and install it.
- You need governed, repeatable installation and upgrades across projects/stacks.

**When NOT to use it / alternatives:** For building the product itself, use the relevant tools plus **Foundry DevOps**. For one-off resource copying within a stack, ordinary project tools suffice.

## Key concepts & terminology

- **Product** — A versioned, installable bundle of Foundry resources.
- **Storefront** — The browsable Marketplace catalog.
- **Installation** — Deploying a product into a project/environment via a guided flow.
- **Upgrade** — Moving an installation to a newer release.
- **Release channel** — A track (e.g., stable/beta) controlling which releases are offered.
- **Maintenance window** — A scheduled time for applying upgrades with minimal disruption.

## Core capabilities / features

- **Discoverability** — Browse and search available products in a storefront.
- **Guided installation** — Step-by-step flows that map inputs and wire up resources.
- **Automated upgrades** — Apply new releases automatically within maintenance windows.
- **Release channels** — Separate stable from experimental distributions.
- **Configuration mapping** — Connect a product's expected inputs to local sources/data.
- **Governed deployment** — Installs respect target-environment permissions and markings.

## How it works / typical workflow

1. **Browse Marketplace** and select a product.
2. **Start the guided installation** into a target project.
3. **Map inputs/configuration** (sources, datasets, parameters) to your environment.
4. **Install**; the product's resources are deployed and wired up.
5. **Choose a release channel** and **maintenance window** for upgrades.
6. **Receive upgrades** automatically per your settings.

## Example

A central team publishes a "Demand Forecasting" product (pipelines + ontology + Workshop app). A regional team opens **Marketplace**, runs the **guided install** into their project, maps their local sales source as the input, and the whole solution stands up in minutes. They subscribe to the **stable** channel, so future improvements arrive during their weekly maintenance window.

## How it connects to the rest of Foundry

- **Foundry DevOps** — Produces and versions the products Marketplace distributes.
- **All resource types** — Installed products can include datasets, pipelines, ontologies, and apps.
- **Projects & permissions** — Installations land in governed projects.
- **Data Lineage / Data Health** — Validate and monitor installed pipelines.

## Tips & gotchas for learners

- **Marketplace installs; DevOps builds** — they're two halves of product delivery.
- **Map inputs carefully** — a product needs to be connected to your local data to work.
- **Use release channels** to avoid pulling experimental changes into production.
- **Maintenance windows** keep upgrades from disrupting users.
- **Installed products are governed** like any other resources in the target project.

## Official documentation

- [Marketplace: Overview](https://www.palantir.com/docs/foundry/marketplace/overview)
- [Marketplace: Foundry products](https://www.palantir.com/docs/foundry/marketplace/foundry-products)
- [Foundry DevOps: Overview](https://www.palantir.com/docs/foundry/foundry-devops/overview)
