<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · PRODUCT DELIVERY</b><br>
<span style="font-size:22px"><b>Marketplace</b></span><br>
<span style="color:#ABB3BF">A Foundry-native storefront for discovering, installing, and managing versioned data products across enrollments.</span>
</td></tr></table>

## What it is

Marketplace is the product distribution layer of Palantir Foundry — a storefront embedded in the Applications Portal where data product builders publish versioned offerings and consumers install them into their own enrollments. Products package Foundry resources (applications, pipelines, ontology entities, functions) together with declared input dependencies, so consumers can deploy a working solution by mapping a small number of data connections. Marketplace sits within the broader **Product Delivery** toolchain alongside Foundry DevOps, which handles product creation and release.

---

## How it works

### Core objects

| Object | Description |
|--------|-------------|
| **Store** | A named collection of products. The **Foundry Store** is available to all customers; organizations can run enrollment-specific stores for internal products. |
| **Product** | A versioned, installable bundle of Foundry resources. Each product carries a version number, a changelog, a content manifest, and an inputs declaration. |
| **Input** | A declared dependency (dataset path, object type, pipeline, etc.) that a consumer must map to an existing resource before installation proceeds. |
| **Installation** | A live, deployed instance of a product inside a specific project or folder in the consumer's enrollment. |
| **Linked product** | An upstream product whose output content automatically satisfies a downstream product's inputs, enabling modular, composable workflows. |

### End-to-end mechanics

1. **Publish (producer side, via Foundry DevOps).** A product builder packages Foundry resources into a product artifact in Foundry DevOps, declares inputs, assigns a semantic version, and publishes it to one or more release channels (`Release`, `Test`, `Stable`). Foundry products (cross-enrollment, Apollo-managed) additionally embed all dependency metadata into a self-contained package.

2. **Discover.** A consumer navigates to Marketplace via the Applications Portal, browses stores, and opens a product listing. The listing surfaces version history, an overview written by the builder, a content preview (which resources will deploy), and a changelog diff between versions. Featured products are curated by store owners and appear prominently.

3. **Initiate installation.** The consumer clicks **Install**. Marketplace creates an **installation draft** and opens a guided, multi-step wizard.

4. **Configure installation mode.** The wizard first sets:
   - **Production mode** — project is locked after installation so content cannot be manually edited; automatic upgrades are safe.
   - **Bootstrap mode** — project is editable after installation; useful when consumers intend to customize.
   - **Singleton mode** — only one installation of this product is permitted per enrollment.
   - An optional **installation suffix** scopes the project name for disambiguation.

5. **Map inputs.** Marketplace enumerates every declared input. The consumer fulfills each by pasting a resource path, selecting a linked product installation, or generating a temporary placeholder for datasets that do not yet exist. A blue checkmark confirms a valid mapping. Inputs can also be prefixed (e.g., `DEV_`) to namespace ontology entities.

6. **Review and validate.** A summary page lists every resource about to be created. Validation errors (missing inputs, incompatible versions) surface here and must be resolved before proceeding.

7. **Install.** Clicking **Install** submits the draft and launches a background resource-creation job. Foundry provisions all declared content, wires inputs to the mapped resources, and registers the new installation.

8. **Manage ongoing lifecycle.** Post-installation, each installation entry tracks:
   - The **release channel** it follows (`Release`, `Test`, or `Stable`).
   - An optional **automatic upgrade** toggle (beta) that applies new versions matching the channel without manual intervention.
   - **Maintenance windows** that constrain when automatic upgrades apply (either "Always open" or a scheduled window).
   - A **lock/unlock** toggle governing whether consumers can fork or edit installed content.

9. **Upgrade flow.** When a new version is tagged on the tracked release channel, Marketplace surfaces a banner. The consumer reviews changes, re-maps any new or changed inputs, resolves validation errors, and confirms. Manual edits to installed content are overwritten by upgrades. Major version bumps (semantic versioning) signal breaking changes; all downstream linked products must be repackaged by their builders before those consumers can upgrade.

10. **Linked products graph.** Foundry DevOps auto-detects link relationships by inspecting source entities during packaging. At install time, the consumer can view a dependency graph showing connected installations. Installing a multi-product graph proceeds as a single job; pre-existing upstream installations serve as inputs without modification.

---

## User interface

### Overall layout

Marketplace is accessed from the <span style="color:#8ABBFF"><b>Applications Portal</b></span> sidebar. The main surface is a two-area layout:

- <span style="color:#8ABBFF"><b>Left: Store browser</b></span> — a scrollable panel (background <span style="color:#1C2127">#1C2127</span>) listing available stores with product tiles. Featured products appear at the top of each store section.
- <span style="color:#8ABBFF"><b>Right: Product detail panel</b></span> — opens when a product tile is clicked, showing tabbed content: **Overview**, **Versions**, **Changelog**, **Content**, and **Inputs**.

### Installation wizard

The wizard is a full-screen stepped flow with a left-side step indicator and a main content area:

<table style="background:#1C2127;border:1px solid #383E47;border-radius:6px;padding:12px;width:100%">
<tr>
<td style="color:#ABB3BF;padding:6px 10px;font-size:13px"><b>Step</b></td>
<td style="color:#ABB3BF;padding:6px 10px;font-size:13px"><b>Panel label</b></td>
<td style="color:#ABB3BF;padding:6px 10px;font-size:13px"><b>Key UI element</b></td>
</tr>
<tr>
<td style="color:#fff;padding:6px 10px">1</td>
<td style="color:#fff;padding:6px 10px">General</td>
<td style="color:#fff;padding:6px 10px">Mode selector (Production / Bootstrap / Singleton), suffix text input, location picker</td>
</tr>
<tr>
<td style="color:#fff;padding:6px 10px">2</td>
<td style="color:#fff;padding:6px 10px">Inputs</td>
<td style="color:#fff;padding:6px 10px">Input rows with resource path field; <span style="color:#238551"><b>● mapped</b></span> / <span style="color:#CD4246"><b>● unmapped</b></span> chips; "View graph" linked-product selector</td>
</tr>
<tr>
<td style="color:#fff;padding:6px 10px">3</td>
<td style="color:#fff;padding:6px 10px">Content</td>
<td style="color:#fff;padding:6px 10px">Read-only manifest of resources to be created; optional ontology prefix input</td>
</tr>
<tr>
<td style="color:#fff;padding:6px 10px">4</td>
<td style="color:#fff;padding:6px 10px">Review</td>
<td style="color:#fff;padding:6px 10px">Validation error list; <span style="color:#2D72D2"><b>Install</b></span> button activates only when all errors resolved</td>
</tr>
</table>

### Installations view

The **Installations** tab (accessible from the Marketplace navigation) displays a table of all active installations with columns for product name, version, release channel, and location. Each row has an ellipsis menu exposing: **View installation**, **Upgrade**, **Change version**, **Lock/Unlock**, **Delete installation permanently**.

Status chips follow Blueprint colors:

<span style="color:#238551"><b>● Installed</b></span> · <span style="color:#C87619"><b>● Upgrade available</b></span> · <span style="color:#CD4246"><b>● Error</b></span> · <span style="color:#2D72D2"><b>● Installing</b></span>

### Foundry products Control Panel extension

For <span style="color:#8ABBFF"><b>Foundry products</b></span> (cross-enrollment, Apollo-managed), administrators access a dedicated **Control Panel** extension showing all product installations across the organization, their Apollo-managed status, and a drill-down for troubleshooting deployment or upgrade failures. This view is separate from the per-user Installations tab.

---

## Worked example

**Scenario:** A data engineering team has built an alert triage application for car-part quality issues. They publish it as two linked products: a **datasource product** (containing a dataset pipeline) and an **application product** (containing a Workshop app and ontology types, with the datasource output declared as an input).

1. A quality analyst opens Marketplace and searches for `Alert Inbox`. The application product appears in the store. She clicks it and sees the Overview tab describing the triage workflow and the Inputs tab showing one required dataset path.

2. She clicks **Install**, selects **Bootstrap** mode (so her team can customize the app later), and names the installation `QA-Team`.

3. On the Inputs step, she pastes the path to an existing `Car Part Issues - Source` dataset that was already installed from the datasource product. The row turns <span style="color:#238551"><b>● green</b></span>.

4. She optionally types `QA` in the ontology prefix field so all object types are named `QA_CarPartIssue` to avoid collisions with other ontology products.

5. On Review, no errors appear. She clicks **Install**. After a few minutes, indexing completes and the `Marketplace Tutorial - Alert Inbox` application appears in her project.

6. Two weeks later, the product builder publishes `v1.1.0` on the `Stable` channel. An **Upgrade available** banner appears in the analyst's Installations view. She reviews the changelog, confirms no new inputs are required, and applies the upgrade in one click.

---

## Documentation map

The Marketplace section of the Foundry docs covers:

- **Overview** — storefront concepts, stores, products, inputs, content
- **Getting started** — tutorial: install a datasource then an application
- **Products**
  - Browse products — store layout, version selector, recalled versions
  - Install a product — wizard steps, installation modes, input mapping, placeholders
  - Linked products — modular graphs, auto-detected links, cross-store linking, breaking changes
  - Foundry products — cross-enrollment portable products, managed vs. artifact installation, Control Panel extension (beta)
- **Installations** — managing active installs, release channels, automatic upgrades, maintenance windows, lock/unlock, deletion

Closely related tools in the broader Product Delivery category:

- **Foundry DevOps** — create products, manage versions, release channels, publish to Marketplace
- **Apollo** — orchestrates Foundry products installations in managed mode

---

## Official documentation

- [Marketplace · Overview](https://www.palantir.com/docs/foundry/marketplace/overview)
- [Marketplace · Getting started](https://www.palantir.com/docs/foundry/marketplace/getting-started)
- [Marketplace · Browse products](https://www.palantir.com/docs/foundry/marketplace/browse-products)
- [Marketplace · Install a product](https://www.palantir.com/docs/foundry/marketplace/install-product/index.html)
- [Marketplace · Linked products](https://www.palantir.com/docs/foundry/marketplace/linked-products)
- [Marketplace · Installations](https://www.palantir.com/docs/foundry/marketplace/installations)
- [Marketplace · Foundry products](https://www.palantir.com/docs/foundry/marketplace/foundry-products)
