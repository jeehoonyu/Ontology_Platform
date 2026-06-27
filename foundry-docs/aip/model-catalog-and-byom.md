# AIP Model Catalog & Bring Your Own Model

> The AIP Model Catalog is Foundry's central hub for discovering and comparing Palantir-provided LLMs, while Bring Your Own Model (BYOM) lets administrators register external or fine-tuned LLMs so they appear alongside Palantir models across all AIP tools.

## What it is

The **Model Catalog** is an AIP application inside Foundry that lists every large language model available in your enrollment, lets you filter by status or capability, and provides playground environments for side-by-side testing. **Bring Your Own Model (BYOM)** — officially called *registered models* — is the companion capability that lets customers connect their own LLM endpoints (via a REST API source) so those models integrate natively into AIP Logic, Chatbot Studio, Workshop, and other Foundry applications. Together they solve the problem of model sprawl: instead of hard-coding API keys scattered across notebooks and pipelines, all models (Palantir-managed or customer-registered) are governed, rate-limited, and discoverable in one place.

## When to use it

**Model Catalog**
- When evaluating which Palantir-provided LLM fits a use case (cost vs. capability trade-off).
- When you need to check whether a model is Stable vs. Experimental before putting it in production.
- When comparing two models side-by-side on a sample prompt before committing to one.

**BYOM / Registered Models**
- When legal, compliance, or data-residency rules prevent using Palantir-hosted models.
- When your team has fine-tuned a model on proprietary data that lives on your own infrastructure.
- When you want to use a model provider not yet offered by Palantir (e.g., a private Azure OpenAI deployment).

**When NOT to use BYOM**
- If Palantir already provides the model you need (OpenAI, Anthropic, Google, Meta, Mistral are all natively supported) — prefer native models because Palantir can guarantee performance and handles operational concerns.
- If your use case is a custom ML/AI model (classification, regression, etc.) — use **Modeling Objectives** for that; the Model Catalog only covers LLMs.

## Key concepts & terminology

- **Model Catalog** — The AIP application listing all LLMs available in your Foundry enrollment, with filters, playgrounds, and comparison tools.
- **Registered model / BYOM** — A customer-supplied LLM endpoint connected to Foundry via a REST API source and surfaced across AIP applications.
- **Enrollment** — A Foundry deployment instance (your organization's environment). Model availability is scoped to the enrollment.
- **Enrollment administrator** — The Foundry role required to register a new model; controls enrollment-wide settings in Control Panel.
- **Data Connection source (REST API)** — The Foundry connector object that stores the base URL, authentication, and export settings for an external model API.
- **Control Panel** — Foundry's administrative UI where enrollment settings, AIP features, and registered models are managed.
- **Lifecycle status** — A label (Experimental / Stable / Sunset / Deprecated) indicating how production-ready and supported a model is.
- **Rate limits** — Three-tier caps (enrollment → project → user) on requests or tokens per minute for each registered model.
- **Capability toggles** — Per-endpoint flags (Reasoning, Structured outputs, Tool calling) that determine which AIP applications can use a registered model.
- **Modeling Objectives** — The separate Foundry feature for managing custom ML/AI models (not LLMs); complementary to Model Catalog.

## Core capabilities / features

### Model Catalog
- **Homepage discovery** — Filterable grid of all LLMs in your enrollment; filter by lifecycle status (Experimental, Stable, Sunset, Deprecated), type (completion, embedding, vision), and model creator (OpenAI, Anthropic, Google, Mixtral, etc.).
- **Entity pages** — A dedicated page per model with playground sandbox, getting-started resources, and detailed specs.
- **Comparison page** — Run the same prompt against two or more models side by side to evaluate quality and latency before committing.
- **Lifecycle transparency** — Clear labeling prevents teams from accidentally building on models that are about to be deprecated.

### Supported LLMs (Palantir-provided)
Palantir natively supports models from: **xAI** (Grok 3/4 series), **OpenAI** (GPT-4o, GPT-4.1, GPT-5 series, o1/o3/o4), **Anthropic** (Claude 3–4.x Haiku/Sonnet/Opus), **Meta** (Llama 3–4 series), **Google** (Gemini 2.0–3.1), and **Mistral/Mixtral**. Text embedding models include `ada`, `text-embedding-3-large/small`, and Snowflake Arctic Embed. Regional availability (US, EU, UK, CA, AU, JP, etc.) varies by model.

### BYOM / Registered Models
- **REST API integration** — Any model endpoint reachable via HTTP (including private Azure OpenAI, self-hosted Llama deployments, etc.) can be registered.
- **Permission decoupling** — Once registered, the model's Data Connection source is decoupled from end-user access. Users only need Control Panel access, not Data Connection permissions.
- **Three-tier rate limiting** — Enrollment-level caps set the ceiling; project-level defaults to 70% of enrollment limits; per-user caps control individual consumption in AI FDE and AIP Analyst.
- **Capability declaration** — Administrators explicitly declare whether the model supports Reasoning, Structured outputs, and Tool calling — this determines which AIP applications the model is eligible for.
- **Broad application support** — Registered models appear in: AI FDE, AIP Analyst, AIP Chatbot Studio, AIP Logic, Workshop, and TypeScript Functions in Code Repositories.
- **Cost passthrough** — Palantir charges no platform fee for registered models; billing from the external provider applies directly.

## How it works / typical workflow

**Using Model Catalog (developer)**

1. Open the **Model Catalog** application inside Foundry.
2. Use filters (status, type, creator) on the homepage to narrow the model list.
3. Click a model's entity page to read its specs and open the playground.
4. Use the **Comparison page** to test your actual prompt against two candidate models.
5. Note the model name and lifecycle status, then reference that model in AIP Logic, Chatbot Studio, or Functions.

**Registering a BYOM model (enrollment administrator)**

1. Open **Data Connection** → New source → **REST API**.
2. Enter a name, configure the **Domain base URL**, authentication method (API key, OAuth, etc.), and port.
3. Toggle on **"Enable exports to this source"** — this is required for outbound model calls.
4. Open **Control Panel** → AIP settings → **Registered models** tab.
5. Click **Register a model**, select the REST API source RID from the dropdown.
6. Enter the model provider name, model name, and API endpoint path.
7. Toggle on applicable **capability flags**: Reasoning, Structured outputs, Tool calling.
8. Set **enrollment-level rate limits** (requests/tokens per minute).
9. Enable the model for the full enrollment or restrict to specific user groups.
10. The model now appears in the model selector across all supported AIP applications.

## Example

**Scenario:** Your legal team requires that a contract-summarization workflow use an internally fine-tuned Llama model hosted on your private Azure infrastructure, not Palantir's hosted models.

1. An enrollment admin creates a REST API source in Data Connection pointing to `https://your-azure-endpoint.openai.azure.com`, authenticated via an API key secret.
2. In Control Panel they register the model as provider: `Azure OpenAI`, model name: `ft-llama-contracts-v2`, endpoint path: `/openai/deployments/ft-llama-contracts-v2/chat/completions`.
3. Tool calling and Structured outputs are toggled on; Reasoning is left off.
4. Rate limits are set to 500 requests/min at enrollment level.
5. A developer opens **AIP Logic**, finds `ft-llama-contracts-v2` in the model selector, and builds the summarization workflow — no API keys in code.

## How it connects to the rest of Foundry

- **AIP Logic** — Consumes models from the catalog (both Palantir-provided and registered) as the AI backbone of automated workflows.
- **AIP Chatbot Studio** — Uses the model selector populated by the catalog to choose which LLM powers a conversational agent.
- **Workshop** — Registered models appear in Workshop's AI widget model selectors, enabling no-code builders to use BYO models.
- **TypeScript Functions / Code Repositories** — Registered models are callable from Functions via the same model interface, keeping secrets out of code.
- **Ontology** — AIP Logic workflows that use models typically operate on Ontology objects (reading properties, writing back AI-generated values), connecting model outputs directly to the operational data layer.
- **Resource Management** — Controls project-level rate limit quotas for registered models; administrators adjust defaults here.
- **Modeling Objectives** — The complementary feature for custom ML/AI models (non-LLM); Model Catalog covers only LLMs.
- **Data Connection** — Provides the REST API source infrastructure that underpins BYOM registration.

## Tips & gotchas for learners

- **Only LLMs in Model Catalog** — If you have a custom classification or regression model, look in Modeling Objectives, not the Model Catalog.
- **Enrollment admin required** — BYOM registration is not self-service for developers; it requires an enrollment administrator. Plan for this in project timelines.
- **Exports must be enabled** — Forgetting to toggle "Enable exports to this source" in Data Connection is the most common reason BYOM registration fails.
- **Capability toggles gate application support** — If a registered model does not appear in AIP Analyst, check whether Tool calling and Structured outputs are enabled in Control Panel.
- **AIP Assist is not supported** — Registered models cannot power AIP Assist (the in-IDE code assistant) or Pipeline Builder's Generate/Explain features — only Palantir-hosted models work there.
- **No markings support on BYOM** — Registered models do not support Palantir data markings; avoid them for workflows involving classified or sensitivity-tagged data.
- **Legacy path exists** — There is a legacy function-interface registration method; new projects should use the current REST API source approach (introduced March 2026).
- **Regional availability** — Even Palantir-provided models may be unavailable in your enrollment's region (EU, KSA, IL2-5, etc.). Check the Supported LLMs page before designing a workflow around a specific model.
- **Prefer Stable models for production** — Experimental models may have capacity limits or behavior changes without notice.

## Official documentation

- [AIP Model Catalog — Overview](https://www.palantir.com/docs/foundry/model-catalog/overview)
- [Bring Your Own Model to AIP](https://www.palantir.com/docs/foundry/aip/bring-your-own-model)
- [Administration: Bring Your Own Model](https://www.palantir.com/docs/foundry/administration/bring-your-own-model)
- [Supported LLMs](https://www.palantir.com/docs/foundry/aip/supported-llms)
- [AIP Overview](https://www.palantir.com/docs/foundry/aip/overview)
