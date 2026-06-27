<table><tr>
<td style="background:#111418;color:#ffffff;padding:18px 24px;border-left:8px solid #2D72D2;font-size:15px">
<b style="color:#8ABBFF">PALANTIR · FOUNDRY</b><br>
<span style="font-size:26px;color:#ffffff"><b>How-It-Works & UI Reference</b></span><br>
<span style="color:#ABB3BF">53 deep-dive files — each explains how a Foundry tool works mechanically and describes its user interface, themed in Foundry's real Blueprint colors.</span>
</td></tr></table>

This is the **deep** companion to [`../foundry-docs/`](../foundry-docs/) (which holds shorter study notes). Every file here is built from the **full documentation pages** (overview + core concepts + how-it-works + UI/tutorial sub-pages) and is structured as: **What it is → How it works (mechanics, execution model, data flow) → User interface → Worked example → Documentation map → Official docs.**

> 🎨 **Colors:** these files use inline HTML so Foundry's palette renders in the **VS Code Markdown preview** (open any file and press `Ctrl+Shift+V`). The full palette and rationale are in [THEME.md](THEME.md).
> <span style="color:#2D72D2">**● Primary #2D72D2**</span> · <span style="color:#238551">**● Success #238551**</span> · <span style="color:#C87619">**● Warning #C87619**</span> · <span style="color:#CD4246">**● Danger #CD4246**</span> · surfaces `#111418` / `#1C2127`.

> ℹ️ **Scope note:** Foundry's docs run to thousands of pages. Each file reads its tool's overview plus the deepest concept/how-it-works/UI pages, and lists the remaining sub-pages under **Documentation map** — so the full surface is visible even where a sub-page wasn't expanded inline.

## Recommended reading order

1. **Foundation** — [Object Types](ontology/object-types.md) · [Link Types](ontology/link-types.md) · [Properties](ontology/properties.md) · [Datasets](data-integration/datasets.md)
2. **Get data in & shape it** — [Data Connection](data-integration/data-connection.md) · [Pipeline Builder](data-integration/pipeline-builder.md) · [Transforms](data-integration/transforms.md) · [Schedules](data-integration/schedules.md)
3. **Build the Ontology** — [Action Types](ontology/action-types.md) · [Functions](ontology/functions.md) · [Interfaces](ontology/interfaces.md) · [Ontology Manager](ontology/ontology-manager.md)
4. **Explore & analyze** — [Object Explorer](analytics/object-explorer.md) · [Contour](analytics/contour.md) · [Quiver](analytics/quiver.md) · [Map / GIS](analytics/map-and-gis.md)
5. **Build apps** — [Workshop](applications/workshop.md) · [Object Views](ontology/object-views.md) · [Automate](applications/automate.md)
6. **AI** — [AIP Logic](aip/aip-logic.md) · [Agent Studio](aip/aip-agent-studio.md) · [Assist](aip/aip-assist.md) · [Evals](aip/aip-evals.md)
7. **Develop & operate** — [OSDK](dev-toolchain/ontology-sdk-osdk.md) · [Data Health](observability/data-health-and-monitoring.md) · [Projects & Permissions](security/projects-and-permissions.md) · [Marketplace](delivery/marketplace.md)

## Index

### <span style="color:#2D72D2">AI Platform (AIP)</span>
[AIP Logic](aip/aip-logic.md) · [Agent / Chatbot Studio](aip/aip-agent-studio.md) · [AIP Assist](aip/aip-assist.md) · [AIP Evals](aip/aip-evals.md) · [Document Intelligence](aip/aip-document-intelligence.md) · [Model Catalog & BYOM](aip/model-catalog-and-byom.md) · [Palantir MCP](aip/palantir-mcp.md)

### <span style="color:#2D72D2">Ontology</span>
[Object Types](ontology/object-types.md) · [Link Types](ontology/link-types.md) · [Properties & Shared Properties](ontology/properties.md) · [Action Types](ontology/action-types.md) · [Functions on Objects](ontology/functions.md) · [Interfaces](ontology/interfaces.md) · [Object Views](ontology/object-views.md) · [Value Types & Structs](ontology/value-types-and-structs.md) · [Ontology Manager](ontology/ontology-manager.md)

### <span style="color:#2D72D2">Data Connectivity & Integration</span>
[Data Connection](data-integration/data-connection.md) · [Syncs & Exports](data-integration/syncs-and-exports.md) · [Pipeline Builder](data-integration/pipeline-builder.md) · [Datasets](data-integration/datasets.md) · [Transforms](data-integration/transforms.md) · [Streaming](data-integration/streaming.md) · [Schedules & Builds](data-integration/schedules.md) · [Data Lineage](data-integration/data-lineage.md) · [Media Sets](data-integration/media-sets.md)

### <span style="color:#2D72D2">Developer Toolchain</span>
[Code Repositories](dev-toolchain/code-repositories.md) · [Code Workspaces](dev-toolchain/code-workspaces.md) · [Code Workbook](dev-toolchain/code-workbook.md) · [Ontology SDK (OSDK)](dev-toolchain/ontology-sdk-osdk.md) · [Platform APIs & SDKs](dev-toolchain/platform-apis-and-sdks.md) · [Compute Modules](dev-toolchain/compute-modules.md)

### <span style="color:#2D72D2">Analytics</span>
[Contour](analytics/contour.md) · [Quiver](analytics/quiver.md) · [Object Explorer](analytics/object-explorer.md) · [Fusion](analytics/fusion.md) · [Notepad & Reports](analytics/notepad.md) · [Map / GIS](analytics/map-and-gis.md)

### <span style="color:#2D72D2">Applications</span>
[Workshop](applications/workshop.md) · [Slate](applications/slate.md) · [Carbon](applications/carbon.md) · [Automate & Autopilot](applications/automate.md)

### <span style="color:#2D72D2">Model Development</span>
[Modeling Objectives](modeling/modeling-objectives.md) · [Model Studio](modeling/model-studio.md) · [Model Integration & Adapters](modeling/model-integration.md) · [Model Deployments](modeling/model-deployments.md)

### <span style="color:#2D72D2">Observability</span>
[Data Health & Monitoring](observability/data-health-and-monitoring.md) · [AIP Observability, Traces & Metrics](observability/aip-observability-and-traces.md)

### <span style="color:#2D72D2">Security & Governance</span>
[Projects, Roles & Permissions](security/projects-and-permissions.md) · [Markings & Classification](security/markings-and-classification.md) · [Cipher](security/cipher.md) · [Audit & Data Governance](security/audit-and-data-governance.md)

### <span style="color:#2D72D2">Product Delivery</span>
[Marketplace](delivery/marketplace.md) · [Foundry DevOps](delivery/foundry-devops.md)

---
<span style="color:#ABB3BF">Built from the official <a href="https://www.palantir.com/docs/foundry/">Palantir Foundry documentation</a>. Colors from Palantir's <a href="https://blueprintjs.com/docs/">Blueprint</a> design system. For authoritative, current detail, always consult the official docs.</span>
