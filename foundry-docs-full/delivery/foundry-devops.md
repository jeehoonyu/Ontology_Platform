<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · PRODUCT DELIVERY</b><br>
<span style="font-size:22px"><b>Foundry DevOps</b></span><br>
<span style="color:#ABB3BF">Package, version, publish, and fleet-manage Foundry resources as installable products across environments and organizations.</span>
</td></tr></table>

## What it is

Foundry DevOps is a first-party Foundry platform capability for bundling any mix of Foundry resources — ontologies, pipelines, Workshop applications, AI models, Carbon workspaces, and more — into versioned, installable **products**. Those products are published to **stores** (curated catalogs), discovered through the **Foundry Marketplace**, and installed into target environments or organizations. DevOps handles automated dependency resolution, staged release channels, and fleet-wide upgrade management so teams can ship and maintain reusable data-backed workflows at scale.

---

## How it works

### Core objects

| Object | What it is |
|---|---|
| **Product** | A named bundle of Foundry resource *outputs* (what is installed) and *inputs* (external requirements the installer must supply). |
| **Store** | A project-backed catalog of products with a shared purpose. Can be *local* (your org) or *remote* (e.g., the Palantir-maintained Foundry Store). |
| **Installation** | One deployed instance of a product, created when an installer fulfills all required inputs. A single product can have many installations. |
| **Release channel** | A tag applied to a product version that controls which installations are eligible to receive it (e.g., `stable`, `beta`, `internal`). |
| **Environment** | A named space (Development / Test / Production) configured in DevOps Settings; governs which installations belong to which stage. |

### End-to-end mechanics

1. **Build a product draft.** A product builder opens the DevOps application, selects (or creates) a store, and clicks **New product**. Resources are added as *outputs* in two modes:
   - **Manual selection** — pick specific datasets, ontology objects, transforms, models, or apps from the Compass filesystem or the ontology resource picker.
   - **Folder tracking** — point DevOps at a source folder; all outputs in that folder are automatically synced into the product as it evolves.

2. **Dependency resolution.** As outputs are added, DevOps introspects each resource's upstream dependencies. Resources that are not themselves outputs become *inputs* — placeholders the installer must wire to existing data on their own instance. The builder can promote any input to an output if the resource should travel with the product rather than be supplied externally.

3. **Validation.** The draft view flags unsupported resource types (e.g., Data Connection sources, Code Workbook workbooks, Fusion sheets) with inline errors. The **Actions → Drop all failed to package** option bulk-removes them before publishing.

4. **Publish a version.** Clicking **Publish** opens a changelog dialog. The builder documents changes and assigns the new version to one or more release channels. From this point the version is visible in the store to users with view or edit access.

5. **Marketplace discovery and installation.** Installers browse the Marketplace, find a product, and initiate installation. DevOps resolves upstream product dependencies and presents them in install order. The installer fills required inputs (e.g., pointing the product's pipeline at local datasets) and optionally configures **release channels** and **maintenance windows** that govern future automatic upgrades.

6. **Fleet management across environments.** Under the **Environments** tab, the DevOps application shows every installation of every product across all configured spaces. Operators can navigate to any installation to view its current version, upgrade it, change its release channel, or lock it against automatic upgrades — all from a single pane of glass.

7. **Release propagation.** When a builder publishes a new version on a release channel, all installations subscribed to that channel and within their configured maintenance window automatically receive the upgrade. Upstream products must be upgraded before downstream dependents to preserve correct resource resolution.

8. **Build hydration.** Installation settings include an optional **build settings** flag that triggers automatic hydration of datasets and models immediately after install, so the product is immediately operational without a manual compute trigger.

---

## User interface

Foundry DevOps is accessed as a standalone application within Foundry. The layout follows Foundry's standard Blueprint-themed shell.

### Overall layout

- <span style="color:#8ABBFF"><b>Left sidebar</b></span> — primary navigation: **Products**, **Stores**, **Marketplace**, **Environments**, **Settings**.
- <span style="color:#8ABBFF"><b>Main panel</b></span> (background <span style="color:#ABB3BF">`#1C2127`</span>) — context-sensitive workspace for the selected section.
- <span style="color:#8ABBFF"><b>Top bar</b></span> — breadcrumbs, store selector, publish/action buttons.

### Product draft view

The draft view is the primary authoring surface:

- **Outputs list** — scrollable table of every resource included in the product. Rows show resource name, type icon, and a status chip.
- **Inputs list** — auto-derived list of external dependencies. Each row shows what the installer must supply and whether it can be promoted to an output.
- **Tabs**: <span style="color:#2D72D2">Outputs</span> · <span style="color:#2D72D2">Inputs</span> · <span style="color:#2D72D2">Linked products</span> · <span style="color:#2D72D2">Dependencies</span> · <span style="color:#2D72D2">Documentation</span> · <span style="color:#2D72D2">Settings</span>
- **Filter / Group toolbar** — filter by resource type or error state; toggle **Group by Folder** for a hierarchical view of destination structure.
- **Actions dropdown** — includes bulk operations such as **Drop all failed to package**.

### Status chips in draft view

<table style="background:#1C2127;border:1px solid #383E47;padding:10px;border-radius:4px">
<tr>
<td style="padding:6px 12px"><span style="color:#238551"><b>● ready</b></span></td>
<td style="color:#ABB3BF;padding:6px 12px">Resource validated, will be packaged</td>
</tr>
<tr>
<td style="padding:6px 12px"><span style="color:#C87619"><b>● pending</b></span></td>
<td style="color:#ABB3BF;padding:6px 12px">Dependency resolution in progress</td>
</tr>
<tr>
<td style="padding:6px 12px"><span style="color:#CD4246"><b>● failed</b></span></td>
<td style="color:#ABB3BF;padding:6px 12px">Resource type unsupported or packaging error</td>
</tr>
<tr>
<td style="padding:6px 12px"><span style="color:#2D72D2"><b>● input</b></span></td>
<td style="color:#ABB3BF;padding:6px 12px">Required external dependency for installer</td>
</tr>
</table>

### Environments tab

A grid of installations organized by environment name (Development / Test / Production). Each row shows product name, current version, release channel, and last-upgraded timestamp. Inline actions let operators **Upgrade**, **Edit channel**, or **Lock** without leaving the tab.

### Marketplace

A browsable store front with product cards (thumbnail, description, install count). Each product card links to a full detail page with documentation (rendered from the builder's markdown), version history, and an **Install** button that launches the guided input-fulfillment wizard.

---

## Worked example

**Scenario: Shipping a supply-chain monitoring product to three regional teams.**

1. A data engineer builds a pipeline that ingests warehouse sensor data and a Workshop dashboard that visualizes inventory levels. Both live in a source folder `/products/supply-chain-monitor`.

2. In DevOps, they create a new product in the `Operations` store and enable **folder tracking** on `/products/supply-chain-monitor`. DevOps auto-discovers the pipeline, dashboard, and underlying ontology object type as outputs. The raw sensor dataset is flagged as an **input** because it differs per region.

3. The engineer sets **Installation mode → Production** and enables **Build settings → Auto-hydrate datasets on install**. They document the product with a markdown description and publish version `1.0.0` on the `stable` release channel.

4. Three regional ops managers find the product in Marketplace, each installs it, and each wires the **input** to their regional sensor dataset. DevOps creates three separate installations.

5. Two weeks later the engineer adds a new KPI to the dashboard and publishes `1.1.0` on `stable`. All three installations — subscribed to `stable` with maintenance windows set to weekend nights — automatically upgrade during the next window. The Environments tab shows all three as <span style="color:#238551"><b>● up to date</b></span>.

---

## Documentation map

Sub-pages and sections beneath Foundry DevOps in the Palantir docs:

- **Foundry DevOps / Overview** — high-level feature summary and use cases
- **Foundry DevOps / Products / Create a product** — step-by-step product authoring
- **Foundry DevOps / Products / Create a product (Beta)** — next-generation product creation UI
- **Foundry DevOps / Products / Supported resources** — exhaustive list of packageable resource types and known exclusions
- **Foundry DevOps / Products / Track source folders** — folder-based automatic output syncing
- **Foundry DevOps / Products / Configure input presets** — pre-filled installer input defaults
- **Foundry DevOps / Stores / Manage store permissions** — role-based access for stores
- **Foundry DevOps / Stores / Manage tags** — organizing products with taxonomy tags
- **Foundry DevOps / Products / Import and export** — moving products between Foundry instances
- **Devops core concepts** — canonical definitions for product, store, installation, release channel
- **Release management / Overview** — three-environment (Dev/Test/Prod) release lifecycle
- **Release management / Use DevOps for release management** — step-by-step: environments, packaging, upgrade automation

---

## Official documentation

- [Foundry DevOps — Overview](https://www.palantir.com/docs/foundry/foundry-devops/overview)
- [Foundry DevOps — Supported resources](https://www.palantir.com/docs/foundry/foundry-devops/supported-resources)
- [Foundry DevOps — Create a product](https://www.palantir.com/docs/foundry/foundry-devops/create-products)
- [DevOps — Core concepts](https://www.palantir.com/docs/foundry/devops/core-concepts)
- [DevOps — Overview](https://www.palantir.com/docs/foundry/devops/overview)
- [Release management — Overview](https://www.palantir.com/docs/foundry/devops-release-management/overview)
- [Release management — Use DevOps for release management](https://www.palantir.com/docs/foundry/devops-release-management/use-devops-for-release-management)
