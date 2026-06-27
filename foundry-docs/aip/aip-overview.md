# AIP (AI Platform) — Overview

> Palantir's AI Platform (AIP) is the suite of Foundry tools that lets builders embed large language models (LLMs) into enterprise workflows — from ad-hoc document analysis all the way to fully automated, Ontology-aware AI agents — under the same security and governance model as the rest of Foundry.

## What it is

AIP is not a single tool; it is a coordinated family of applications that share a common foundation: secure LLM access, the Foundry Ontology, and a unified governance layer. Each component addresses a distinct stage of the AI workflow lifecycle — exploring, building, evaluating, deploying, and monitoring. AIP lives inside Foundry and extends every surface area of the platform (pipelines, Workshop apps, Functions, Automate) with AI capabilities. The Ontology acts as the central hub, providing AIP tools with live, governed access to enterprise objects, actions, and data.

## When to use it

- When you want to turn raw documents, emails, or reports into structured Ontology data automatically (Document Intelligence).
- When you need to build an LLM-powered function that reads Ontology objects and writes back edits — without writing Python (AIP Logic).
- When you want to give end-users a natural-language chatbot embedded in a Workshop app (Chatbot Studio).
- When you need a quick, ad-hoc Q&A session over a PDF or report without setting up a full pipeline (Threads).
- When you want to evaluate whether your LLM function is reliable enough for production (Evals).
- When you must use your own fine-tuned or compliance-approved model instead of Palantir-provided models (BYOM).
- When you want external AI IDEs or agents (e.g., GitHub Copilot, Cursor) to query your Foundry data and build apps (MCP).

**When NOT to use AIP directly:** For deterministic, rule-based data transformations, use Pipeline Builder / Code Repositories without LLMs. For traditional ML model training and scoring, use Modeling Objectives rather than the Model Catalog.

## Key concepts & terminology

- **Ontology** — Foundry's semantic layer that represents enterprise entities (objects), relationships, and actions; the data backbone AIP tools read from and write to.
- **AIP Logic function** — A no-code, LLM-backed function that takes Ontology objects or text as input and returns text, objects, or Ontology edits as output.
- **AIP Chatbot** — An interactive assistant built in Chatbot Studio; powered by an LLM plus enterprise data sources and custom tools.
- **AIP Agent** — (older term) An AIP Chatbot; "Agent Studio" was renamed to "Chatbot Studio."
- **Registered model / BYOM** — A customer-owned LLM connected to AIP via a REST API source; appears alongside Palantir-provided models in the model selector.
- **Evaluation suite** — A structured set of test cases and scoring functions used in AIP Evals to measure LLM function reliability.
- **Media set** — A Foundry dataset of documents (PDFs, images) that Document Intelligence extracts content from.
- **MCP (Model Context Protocol)** — Palantir's implementation of the open MCP standard; lets external AI tools access Foundry context (ontology schema, documentation, data) securely.
- **Model Catalog** — The in-platform directory of all available LLMs (Palantir-provided), with lifecycle status, benchmarks, and a sandbox playground.
- **AIP Threads** — A lightweight, chat-style interface for ad-hoc LLM queries over documents; no build required.
- **AIP Assist** — An always-on, context-aware helper embedded in the Foundry UI that answers questions about the platform and your data.

## Core capabilities / features

### AIP Logic
- No-code environment for building LLM-powered functions using prompt templates and Ontology inputs.
- Functions can return plain text, structured Ontology objects, or staged/automatic Ontology edits.
- Supports automation: edits can be applied on a schedule, triggered by events, or queued for human review.
- Integrates directly with Pipeline Builder, Automate, and Scheduler.

### AIP Chatbot Studio (formerly Agent Studio)
- Build interactive chatbots ("AIP Chatbots") backed by LLMs, Ontology context, documents, and custom tools.
- Deploy chatbots inside Workshop apps, via the Marketplace, or externally through the Ontology SDK and Foundry APIs.
- Supports dynamic read/write workflows: chatbots can query objects and trigger Ontology actions.
- Operates under Foundry's role-based and marking-based security — LLMs only see data the user is permitted to see.

### AIP Evals
- Testing framework purpose-built for non-deterministic LLM outputs.
- Create test cases (input/expected output pairs), define evaluation functions (LLM-as-judge, exact match, custom), and run suites against one or multiple target functions.
- Compare results across model versions, prompt iterations, or different LLM backends side by side.
- Embedded in AI FDE (the conversational developer environment) for inline evaluation during development.

### AIP Assist
- An LLM-powered assistant embedded throughout the Foundry UI to help users navigate the platform, understand data, and suggest next steps.
- Can be powered by custom content sources (internal documentation, Ontology data) to give org-specific answers.
- Supports suggested actions that trigger real Ontology operations.

### AIP Document Intelligence
- Extracts structured content from document media sets using traditional OCR or generative VLM (vision language model) strategies.
- Compare extraction strategies side by side with quality metrics (list/table/code block accuracy, token cost, execution time).
- One-click deployment: exports the chosen strategy into a Python Transforms repository, enabling batch pipeline processing.

### Model Catalog
- Central directory of all Palantir-provided LLMs available in the enrollment.
- Models carry lifecycle status labels: Experimental, Stable, Sunset, Deprecated.
- Supports side-by-side model comparison and a sandbox playground for testing prompts before committing to a model.
- Covers completion, embedding, and vision model types from providers including OpenAI, Anthropic, Google, and Palantir-hosted open models (Llama, Mixtral).

### Bring Your Own Model (BYOM / Registered Models)
- Connect any LLM reachable via a standard REST API (OpenAI-compatible endpoint) to Foundry.
- Registered models appear in the same model selector as Palantir-provided models across AIP Logic, Chatbot Studio, Workshop, and Code Repositories (TypeScript functions).
- Supports tool calling, reasoning, structured outputs, vision, and streaming.
- Enrollment administrators control access, rate limits, and usage observability from Control Panel.
- Use case: compliance-mandated models, fine-tuned proprietary models, or models hosted on private cloud infrastructure.

### AIP Threads
- Lightweight, chat-style interface for ad-hoc document analysis — drag in a PDF and ask questions.
- Responses are cited and sourced from the uploaded documents.
- Designed for non-technical users; no pipeline or configuration required.
- Stepping stone: users who outgrow Threads are directed to Chatbot Studio or AIP Logic for more structured, repeatable workflows.

### Palantir MCP (Model Context Protocol)
- Implements the open MCP standard to bridge external AI agents and IDEs (e.g., Cursor, GitHub Copilot) with Foundry.
- External tools gain read access to Ontology schema, application documentation, and data — enabling them to generate code and build Foundry apps with proper context.
- Governed by the same security model as the rest of the platform.

## How it works / typical workflow

1. **Model selection** — Open the Model Catalog to choose an LLM (or register your own via BYOM) that fits your latency, cost, and compliance requirements.
2. **Build a Logic function** — In AIP Logic, define a prompt template, wire in Ontology object properties as inputs, and specify the output (text, structured object, or Ontology edit).
3. **Evaluate** — In AIP Evals, create an evaluation suite: write test cases representing real inputs, pick an evaluation function (LLM judge or exact-match), and run the suite. Iterate on the prompt until metrics are satisfactory.
4. **Surface to users** — Embed the Logic function in a Chatbot Studio chatbot or a Workshop widget, or trigger it automatically via Automate/Scheduler.
5. **Monitor** — Use Foundry's observability tools to track token consumption, latency, and audit trails for every LLM call.
6. **(Optional) Document extraction** — Use Document Intelligence to extract structured data from PDFs into Ontology objects, feeding downstream Logic functions or pipelines.

## Example

**Scenario: Automated vendor contract review**

A procurement team receives hundreds of vendor contracts as PDFs each month. Using AIP:

1. **Document Intelligence** extracts contract terms (expiry date, liability cap, jurisdiction) from each PDF into a `Contract` Ontology object type.
2. An **AIP Logic function** reads each `Contract` object and runs an LLM prompt: *"Given these contract terms, identify any non-standard clauses and classify risk as Low / Medium / High."* The function writes a `risk_classification` property back to the `Contract` object.
3. **AIP Evals** validates the function against 50 manually labeled contracts before release.
4. A **Chatbot Studio** chatbot in the procurement Workshop app lets users ask: *"Show me all High-risk contracts expiring this quarter"* — the chatbot queries the Ontology and returns a cited summary.

No custom Python is required for steps 1–4; the Logic function uses the no-code prompt builder.

```
-- AIP Logic function (conceptual, no-code configuration) --
Input:  Contract object  →  {terms_text: string, jurisdiction: string}
Prompt: "Classify the risk of the following contract terms as Low, Medium,
         or High. Return JSON: {risk: string, rationale: string}."
Output: Ontology edit  →  Contract.risk_classification = "High"
                           Contract.risk_rationale    = "..."
```

## How it connects to the rest of Foundry

- **Ontology** — Every AIP tool reads from and writes to the Ontology. AIP Logic functions are first-class Ontology Functions; they can be called anywhere Functions are supported.
- **Pipeline Builder / Code Repositories** — Document Intelligence deploys directly into a Python Transforms repository; Logic functions can be called from pipeline steps.
- **Workshop** — Chatbot Studio chatbots and Logic functions can be embedded as Workshop widgets. AIP Assist is available in the Workshop builder UI.
- **Automate / Scheduler** — Logic functions can be set to run automatically on a schedule or when an Ontology event is triggered.
- **Ontology SDK** — Chatbots and Logic functions are callable from external TypeScript, Python, or Java applications via the SDK.
- **Functions** — AIP Chatbots can be published as Foundry Functions, making them usable in Evals, Automate, and Code Repositories.
- **Apollo / Rubix** — AIP workloads are deployed and managed by Palantir's Apollo deployment system on Rubix infrastructure, ensuring the same operational guarantees as the rest of Foundry.

## Tips & gotchas for learners

- **AIP Logic vs. Code Repositories:** Logic is no-code and LLM-centric. For deterministic data transformation (joins, aggregations), stick with Python/SQL in Code Repositories. Use Logic when the task genuinely requires language understanding.
- **Model lifecycle matters:** Always check a model's lifecycle status in Model Catalog before building on it. Building on an Experimental or Sunset model risks breakage when Palantir deprecates it.
- **BYOM requires admin setup:** Registering a custom model needs both a Data Connection REST API source AND enrollment-level Control Panel configuration — it is not a self-service action for regular builders.
- **Non-determinism is the norm:** LLM outputs vary between runs. Always run AIP Evals before promoting a Logic function to production, and re-run periodically after prompt or model changes.
- **Security is inherited, not added:** AIP tools automatically inherit Foundry's object-level permissions and markings. An LLM cannot be prompted to bypass them — it only sees data the calling user is authorized to see.
- **Threads is not a replacement for Logic:** Threads is great for one-off exploration. For anything that runs repeatedly, involves Ontology writes, or is user-facing in a Workshop app, build a proper Logic function or Chatbot.
- **Document Intelligence is beta (as of mid-2025):** Check release notes before relying on it in production pipelines.
- **MCP is for developers, not end users:** Palantir MCP is intended to augment developer tooling (IDEs, code agents) — it is not a user-facing feature.

## Official documentation

- [AIP Overview](https://www.palantir.com/docs/foundry/aip/overview)
- [AIP Features](https://www.palantir.com/docs/foundry/aip/aip-features)
- [AIP Architecture Overview](https://www.palantir.com/docs/foundry/architecture-center/aip-architecture)
- [AIP Logic — Overview](https://www.palantir.com/docs/foundry/logic/overview)
- [AIP Chatbot Studio — Overview](https://www.palantir.com/docs/foundry/chatbot-studio/overview)
- [AIP Chatbot Studio — Core Concepts](https://www.palantir.com/docs/foundry/chatbot-studio/core-concepts)
- [AIP Evals — Overview](https://www.palantir.com/docs/foundry/aip-evals/overview)
- [AIP Document Intelligence — Overview](https://www.palantir.com/docs/foundry/document-intelligence/overview)
- [AIP Model Catalog — Overview](https://www.palantir.com/docs/foundry/model-catalog/overview)
- [Bring Your Own Model to AIP](https://www.palantir.com/docs/foundry/aip/bring-your-own-model)
- [AIP Threads — Overview](https://www.palantir.com/docs/foundry/threads/overview)
