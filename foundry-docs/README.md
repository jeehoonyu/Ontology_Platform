# Palantir Foundry — Study Guide

A learner-focused reference covering the major tools and functionalities of [Palantir Foundry](https://www.palantir.com/docs/foundry/). There is **one markdown file per feature**, each following the same structure: *What it is → When to use it → Key concepts → Core capabilities → Typical workflow → Worked example → How it connects → Tips & gotchas → Official docs*.

> Grounding: content is based on the official Palantir Foundry documentation. The AIP and Ontology files were additionally fact-checked against the live docs by a verification pass; always confirm exact UI details against the [official docs](https://www.palantir.com/docs/foundry/), which evolve.

---

## How Foundry fits together (the 60-second mental model)

```
External systems ──► Data Connection (sources/syncs)
                         │
                         ▼
                     Datasets ──► Transforms / Pipeline Builder ──► clean datasets
                         │                                              │
                         ▼                                              ▼
                     Streams (real-time)                          The ONTOLOGY
                                                    (object types · links · actions · functions)
                                                                        │
        ┌───────────────┬───────────────┬───────────────┬─────────────┤
        ▼               ▼               ▼               ▼             ▼
   Workshop /       Analytics       Modeling /        AIP         APIs / OSDK
   apps (Slate,    (Contour,        ML (objectives,  (Logic,     (custom apps)
   Carbon)         Quiver, Map)     deployments)     agents)
        │
        ▼
  Security & governance (permissions · markings · Cipher · audit) wraps EVERYTHING
  Observability (Data Health · traces) and Delivery (Marketplace · DevOps) operate across it all
```

**The Ontology is the center of gravity.** Data flows *up* into it; applications, analytics, ML, and AI all sit *on top* of it.

---

## Recommended learning path

Work through these in order — each builds on the last.

1. **Foundations** — [Ontology overview](ontology/ontology-overview.md) · [Datasets, schemas & transactions](data-integration/datasets.md) · [Data integration overview](data-integration/data-integration-overview.md)
2. **Getting data in** — [Data Connection](data-integration/data-connection.md) · [Syncs & exports](data-integration/syncs-and-exports.md)
3. **Shaping data (no-code first)** — [Pipeline Builder](data-integration/pipeline-builder.md) · [Schedules & builds](data-integration/schedules.md) · [Data Lineage](data-integration/data-lineage.md)
4. **Shaping data (code)** — [Code Repositories](dev-toolchain/code-repositories.md) · [Transforms](data-integration/transforms.md) · [Code Workbook](dev-toolchain/code-workbook.md)
5. **Building the Ontology** — [Object types](ontology/object-types.md) · [Link types](ontology/link-types.md) · [Properties](ontology/properties.md) · [Action types](ontology/action-types.md) · [Functions](ontology/functions.md)
6. **Exploring & analyzing** — [Object Explorer](analytics/object-explorer.md) · [Contour](analytics/contour.md) · [Quiver](analytics/quiver.md) · [Map / GIS](analytics/map-and-gis.md)
7. **Building applications** — [Workshop](applications/workshop.md) · [Object views](ontology/object-views.md) · [Automate](applications/automate.md)
8. **AI on your data** — [AIP overview](aip/aip-overview.md) · [AIP Logic](aip/aip-logic.md) · [AIP Agent Studio](aip/aip-agent-studio.md)
9. **Machine learning** — [Modeling Objectives](modeling/modeling-objectives.md) · [Model deployments](modeling/model-deployments.md)
10. **Custom development** — [Ontology SDK (OSDK)](dev-toolchain/ontology-sdk-osdk.md) · [Platform APIs & SDKs](dev-toolchain/platform-apis-and-sdks.md)
11. **Operate & govern** — [Data Health & monitoring](observability/data-health-and-monitoring.md) · [Projects & permissions](security/projects-and-permissions.md) · [Markings](security/markings-and-classification.md) · [Marketplace](delivery/marketplace.md)

---

## Full index by category

### 🤖 AIP — AI Platform
| File | What it is |
|---|---|
| [AIP overview](aip/aip-overview.md) | The whole AIP suite and how the pieces fit |
| [AIP Logic](aip/aip-logic.md) | No-code builder for LLM-powered functions/workflows |
| [AIP Agent Studio](aip/aip-agent-studio.md) | Build conversational AI agents with tools & retrieval |
| [AIP Assist](aip/aip-assist.md) | In-platform AI assistant for building in Foundry |
| [AIP Evals](aip/aip-evals.md) | Evaluation framework for LLM logic and agents |
| [AIP Document Intelligence](aip/aip-document-intelligence.md) | Extract structured data from documents (OCR/VLM) |
| [Model Catalog & BYOM](aip/model-catalog-and-byom.md) | Supported LLMs + bring-your-own-model |
| [Palantir MCP](aip/palantir-mcp.md) | Let AI IDEs/agents build in Foundry via MCP |

### 🧬 Ontology
| File | What it is |
|---|---|
| [Ontology overview](ontology/ontology-overview.md) | The semantic layer: objects, links, actions, functions |
| [Object types](ontology/object-types.md) | Schema definitions of real-world entities |
| [Link types](ontology/link-types.md) | Relationships between object types |
| [Properties](ontology/properties.md) | Typed attributes & shared property types |
| [Action types](ontology/action-types.md) | Governed writeback to the Ontology |
| [Functions](ontology/functions.md) | TypeScript/Python logic on objects |
| [Interfaces](ontology/interfaces.md) | Polymorphic shared capabilities across types |
| [Object views](ontology/object-views.md) | Configurable object detail pages |
| [Value types & structs](ontology/value-types-and-structs.md) | Custom value types and composite properties |
| [Ontology Manager](ontology/ontology-manager.md) | Admin app: branching, proposals, governance |

### 🔌 Data Connectivity & Integration
| File | What it is |
|---|---|
| [Data integration overview](data-integration/data-integration-overview.md) | How data gets in/out and is transformed |
| [Data Connection](data-integration/data-connection.md) | Connect to external systems (sources & agents) |
| [Syncs & exports](data-integration/syncs-and-exports.md) | Import/export data to/from sources |
| [Pipeline Builder](data-integration/pipeline-builder.md) | Visual no-code batch & streaming pipelines |
| [Datasets](data-integration/datasets.md) | Versioned data: schemas, transactions, branches |
| [Transforms](data-integration/transforms.md) | Code-first pipelines (Python/Java/SQL) |
| [Streaming](data-integration/streaming.md) | Real-time streams and streaming pipelines |
| [Schedules](data-integration/schedules.md) | Automating builds (time/event triggers) |
| [Data Lineage](data-integration/data-lineage.md) | Dependency graph & impact analysis |
| [Media sets](data-integration/media-sets.md) | Unstructured/binary data (images, PDFs, audio) |

### 🛠️ Developer Toolchain
| File | What it is |
|---|---|
| [Code Repositories](dev-toolchain/code-repositories.md) | Git-backed transform/function authoring |
| [Code Workspaces](dev-toolchain/code-workspaces.md) | Hosted VS Code / Jupyter IDEs |
| [Code Workbook](dev-toolchain/code-workbook.md) | Interactive graph-based Python/R/SQL analysis |
| [Ontology SDK (OSDK)](dev-toolchain/ontology-sdk-osdk.md) | Typed SDKs generated from the Ontology |
| [Platform APIs & SDKs](dev-toolchain/platform-apis-and-sdks.md) | REST APIs + Python/TS SDKs for automation |
| [Compute Modules](dev-toolchain/compute-modules.md) | Bring-your-own-container services |
| [Foundry DevOps](dev-toolchain/foundry-devops.md) | Package, version & promote products |

### 📊 Analytics & Application Building
| File | What it is |
|---|---|
| [Contour](analytics/contour.md) | Point-and-click tabular analysis at scale |
| [Quiver](analytics/quiver.md) | Object & time-series analysis, point-click ML |
| [Object Explorer](analytics/object-explorer.md) | Search & explore Ontology objects |
| [Fusion](analytics/fusion.md) | Spreadsheets wired to the Ontology |
| [Notepad & Reports](analytics/notepad-and-reports.md) | Documents with live embedded artifacts |
| [Map / GIS & Vertex](analytics/map-and-gis.md) | Geospatial/temporal analysis & graph view |

### 🖥️ Operational Applications
| File | What it is |
|---|---|
| [Workshop](applications/workshop.md) | Flagship no-code operational app builder |
| [Slate](applications/slate.md) | Low-code custom app builder |
| [Carbon](applications/carbon.md) | Unified workspace tying apps together |
| [Automate & Autopilot](applications/automate.md) | Condition-based automations |

### 🧠 Model Development
| File | What it is |
|---|---|
| [Modeling Objectives](modeling/modeling-objectives.md) | Mission control for the ML lifecycle |
| [Model Studio](modeling/model-studio.md) | Point-and-click model training |
| [Model integration & adapters](modeling/model-integration-and-adapters.md) | Bring any model into Foundry |
| [Model deployments](modeling/model-deployments.md) | Serve models live or in batch |

### 📡 Observability
| File | What it is |
|---|---|
| [Data Health & monitoring](observability/data-health-and-monitoring.md) | Health checks & monitoring views for data |
| [AIP observability & traces](observability/aip-observability-and-traces.md) | Traces, metrics & logs for logic/AI workflows |

### 🔐 Security & Governance
| File | What it is |
|---|---|
| [Projects, roles & permissions](security/projects-and-permissions.md) | Core access model & hierarchy |
| [Markings & classification](security/markings-and-classification.md) | Mandatory controls & row/column security |
| [Cipher](security/cipher.md) | Encrypt/tokenize sensitive values |
| [Audit & data governance](security/audit-and-data-governance.md) | Audit logs, scanning, retention, approvals |

### 🚀 Product Delivery
| File | What it is |
|---|---|
| [Marketplace](delivery/marketplace.md) | Discover, install & upgrade data products |

---

## Cross-cutting glossary (terms you'll see everywhere)

- **Ontology** — Foundry's semantic layer of objects, links, actions, and functions sitting on top of datasets.
- **Object type / object** — A schema (like a table) / a single instance (like a row).
- **Link type** — A defined relationship between two object types.
- **Action** — Governed writeback that changes objects/links.
- **Function** — Reusable TypeScript/Python logic on the Ontology.
- **Dataset** — Versioned, governed tabular/file data; the unit pipelines read and write.
- **Transaction** — An atomic commit to a dataset (SNAPSHOT/APPEND/UPDATE/DELETE).
- **Pipeline / transform / build** — The graph that produces data / the step / one execution.
- **RID** — Resource Identifier; the canonical ID of any Foundry resource.
- **Marking** — A mandatory access control that overrides ordinary role permissions.
- **Project** — The primary container and permission boundary for resources.
- **OSDK** — The typed SDK generated from your Ontology for custom apps.

---

*Generated as a personal study reference. For authoritative, current details always consult the [official Palantir Foundry documentation](https://www.palantir.com/docs/foundry/).*
