# Foundry DevOps

> Foundry DevOps is the suite for packaging, versioning, releasing, and promoting Foundry resources as products across branches and environments — the platform's application lifecycle management.

## What it is

As solutions mature, you need to move them reliably from development to production, and from one Foundry environment to another, without hand-rebuilding everything. Foundry DevOps provides the tooling to bundle related resources (datasets, pipelines, ontologies, apps) into versioned **products**, manage their releases, and promote them safely. It's closely tied to **Marketplace**, which is the storefront where these products are discovered and installed.

## When to use it

- You're packaging a solution to deploy across multiple projects or environments.
- You need repeatable, versioned releases instead of manual copying.
- You're publishing a reusable product for others to install via Marketplace.

**When NOT to use it / alternatives:** For a single one-off pipeline in one place, ordinary projects/branches suffice. DevOps shines when you need productization and promotion.

## Key concepts & terminology

- **Product** — A versioned bundle of Foundry resources packaged for installation.
- **Release** — A published version of a product.
- **Supported resources** — The resource types that can be included in a product.
- **Installation** — Deploying a product into a target environment/project.
- **Upgrade** — Moving an installation to a newer release, with maintenance windows.
- **Release channel** — A track (e.g., stable/beta) controlling which releases install.
- **Marketplace** — The storefront for discovering and installing products.

## Core capabilities / features

- **Productization** — Bundle datasets, pipelines, ontologies, and apps into one deployable unit.
- **Versioned releases** — Cut and track releases for reproducible deployments.
- **Promotion across environments** — Move solutions from dev to prod consistently.
- **Upgrade management** — Schedule upgrades with maintenance windows and channels.
- **Supported-resource coverage** — Broad set of resource types can be packaged.
- **Integration with Marketplace** — Publish and install through the storefront.

## How it works / typical workflow

1. **Develop** your solution (pipelines, ontology, apps) in a project.
2. **Package** the resources into a **product**.
3. **Cut a release** (a versioned snapshot).
4. **Publish** to Marketplace (or an internal store).
5. **Install** the product into target environments/projects.
6. **Manage upgrades** via release channels and maintenance windows.

## Example

A team builds a "Supply Chain Control Tower" — pipelines, an ontology, and a Workshop app. They package it as a **product**, cut **v1.2.0**, and publish to Marketplace. Other business units **install** it into their own projects and receive **upgrades** on the stable channel during scheduled maintenance windows.

## How it connects to the rest of Foundry

- **Marketplace** — The storefront where DevOps products are published/installed.
- **All resource types** — Datasets, pipelines, ontologies, and apps can be packaged.
- **Data Lineage** — Helps validate product dependencies before packaging.
- **Security** — Promotion respects markings and permissions in target environments.

## Tips & gotchas for learners

- **Productize when you'll deploy repeatedly** — not for one-off work.
- **Versioning is the point** — releases make deployments reproducible and rollback-able.
- **Mind environment differences** — sources/credentials may differ across stacks.
- **Use release channels** to separate stable from experimental installs.

## Official documentation

- [Foundry DevOps: Overview](https://www.palantir.com/docs/foundry/foundry-devops/overview)
- [Foundry DevOps: Supported resources](https://www.palantir.com/docs/foundry/foundry-devops/supported-resources)
- [Marketplace: Overview](https://www.palantir.com/docs/foundry/marketplace/overview)
