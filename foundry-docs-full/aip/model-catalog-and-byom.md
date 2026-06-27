<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · AI PLATFORM</b><br>
<span style="font-size:22px"><b>AIP Model Catalog &amp; BYOM</b></span><br>
<span style="color:#ABB3BF">Centralized discovery, lifecycle management, and bring-your-own-model registration for all LLMs available in a Foundry enrollment.</span>
</td></tr></table>

## What it is

The **AIP Model Catalog** is a first-party Foundry application that serves as the single authoritative source for every Palantir-provided large language model available in an enrollment — covering discovery, playground testing, deprecation tracking, and launch into downstream builder tools. **BYOM (Bring Your Own Model)**, surfaced as *registered models* in Control Panel, extends that surface by letting enrollment administrators connect externally-hosted or proprietary LLMs to the same AIP toolchain, giving them the same model-selector presence as native Palantir-managed models. Together the two capabilities form the model layer that every AIP builder tool (AIP Logic, AIP Chatbot Studio, AI FDE, AIP Analyst, Workshop, TypeScript functions) consumes at runtime.

---

## How it works

### Model Catalog — mechanics

1. **Admin enablement.** An enrollment administrator opens <span style="color:#8ABBFF">Control Panel → AIP settings → Models</span> and enables individual models for the enrollment. Until enabled, a model is invisible to builders. Legal acknowledgment gates certain providers (e.g., xAI/Grok, some Anthropic tiers).

2. **Catalog indexing.** Once enabled, Foundry writes a model record into the enrollment's catalog index. Each record carries: provider name, model name/version, lifecycle stage, context-window size, training cutoff, capability flags (reasoning, structured outputs, tool calling, vision, embedding), and georestriction metadata.

3. **Lifecycle tagging.** Every model is tagged with one of four stages that Foundry enforces platform-wide:
   - <span style="color:#9D3F9D"><b>Experimental</b></span> — unstable API, limited support; for exploration only.
   - <span style="color:#238551"><b>Stable</b></span> — production-ready, fully supported.
   - <span style="color:#C87619"><b>Sunset</b></span> — deprecated path announced; existing workflows continue but new usage is discouraged.
   - <span style="color:#CD4246"><b>Deprecated</b></span> — model endpoint removed; callers must migrate.

4. **Playground execution.** From a model's entity page, a builder submits a prompt. Foundry routes the request through its inference gateway, which authenticates against the relevant provider (OpenAI, Azure OpenAI, Anthropic, AWS Bedrock, GCP Vertex, xAI, Palantir-self-hosted Llama), applies enrollment-level rate limits, and streams the completion back. The playground does not persist conversations to datasets — it is strictly ephemeral.

5. **Model comparison.** The Comparison page accepts two model IDs and a shared prompt/task, fires parallel requests through the same inference gateway, and renders responses side-by-side with latency metadata. No state is written to the Ontology.

6. **Downstream consumption.** When a builder configures an LLM node in AIP Logic, selects a model in AIP Chatbot Studio, or writes a `getLanguageModel` call in a TypeScript function, the call resolves to the model record in the catalog. At runtime, Foundry's AIP inference gateway handles provider authentication transparently — the builder never holds provider credentials.

### BYOM / Registered models — mechanics

1. **Create a Data Connection REST API source.** The administrator defines a new source in <span style="color:#8ABBFF">Data Connection</span> specifying the provider's base domain URL, authentication method (API key, OAuth2, or bearer token), and port. This source RID is the credentials anchor.

2. **Register the model in Control Panel.** Navigate to <span style="color:#8ABBFF">Control Panel → AIP settings → Registered models → Register a model</span>. The form requests:
   - The REST API source RID created above.
   - Provider name (free-text label), model name (must match the provider's API identifier exactly), and endpoint path (e.g., `/v1/chat/completions`).
   - Capability declarations: reasoning, structured outputs, tool calling.
   - Rate limits — enrollment-level (requests/tokens per minute) and, optionally, per-user caps.

3. **Credential severance.** Once saved, Foundry severs the link between the Data Connection source's ACL and end-user access. End users never hold the source's permissions; access is governed entirely by Control Panel enrollment/group grants. This is a key security boundary.

4. **Enrollment distribution.** The administrator grants access to the entire enrollment or to specific user groups. The registered model then appears in every AIP model selector across AI FDE, AIP Analyst, AIP Chatbot Studio, AIP Logic, Workshop, and TypeScript Code Repositories — identical in appearance to Palantir-provided models.

5. **Rate limit hierarchy.** Three tiers enforce capacity:
   - Enrollment-level limits set the absolute ceiling.
   - Project-level limits default to 70 % of the enrollment ceiling and are adjustable in <span style="color:#8ABBFF">Resource Management → AIP usage and limits</span>.
   - User-level limits apply in user-attributed surfaces (AI FDE, AIP Analyst).

6. **Cost routing.** Palantir does not meter BYOM calls; the model provider bills the customer directly. Resource Management shows call volume for observability but not cost figures.

7. **Unsupported surfaces.** AIP Assist (including Code Repository code assist) and Pipeline Builder's Generate/Explain features do not support registered models as of mid-2026.

---

## User interface

### Model Catalog application

<table style="border-collapse:collapse;width:100%">
<tr style="background:#1C2127">
  <th style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47;text-align:left">Screen</th>
  <th style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47;text-align:left">What you see</th>
</tr>
<tr style="background:#111418">
  <td style="padding:8px 12px;border-bottom:1px solid #383E47"><span style="color:#8ABBFF"><b>Homepage / Model Grid</b></span></td>
  <td style="padding:8px 12px;border-bottom:1px solid #383E47">Cards for every enabled LLM. Left-rail filter panel by lifecycle stage, model type (completion / embedding / vision), and creator/provider. Each card shows provider logo, model name, context window, and a lifecycle chip.</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border-bottom:1px solid #383E47"><span style="color:#8ABBFF"><b>Model Entity Page</b></span></td>
  <td style="padding:8px 12px;border-bottom:1px solid #383E47">Three tabs: <b>Playground</b> (text/vision prompt editor + streaming response pane), <b>How to Use It</b> (resource-creation launchers for Functions, Transforms, Marketplace templates), <b>Model Description</b> (context window, training cutoff, capability matrix).</td>
</tr>
<tr style="background:#111418">
  <td style="padding:8px 12px;border-bottom:1px solid #383E47"><span style="color:#8ABBFF"><b>Comparison Page</b></span></td>
  <td style="padding:8px 12px;border-bottom:1px solid #383E47">Two-column layout. Each column has a model picker (dropdown). A shared prompt bar at the top fires to both simultaneously. Response panes render side-by-side with per-column latency indicators.</td>
</tr>
</table>

**Lifecycle chips** rendered on model cards:

<span style="color:#9D3F9D"><b>● Experimental</b></span> · <span style="color:#238551"><b>● Stable</b></span> · <span style="color:#C87619"><b>● Sunset</b></span> · <span style="color:#CD4246"><b>● Deprecated</b></span>

### Control Panel — Registered models tab

The <span style="color:#8ABBFF">AIP settings</span> extension in Control Panel exposes a <span style="color:#8ABBFF">Registered models</span> tab listing all BYOM entries in a table: model name, provider label, REST API source RID, enabled/disabled toggle, and an edit/delete action menu. The <span style="color:#2D72D2"><b>Register a model</b></span> button opens a multi-step drawer:

1. **Source selection** — searchable picker over all Data Connection REST API sources the admin has Owner/Editor access to.
2. **Model details** — text fields for provider name, model name, endpoint path.
3. **Capabilities** — checkbox grid (reasoning, structured outputs, tool calling).
4. **Rate limits** — numeric fields for enrollment TPM/RPM and user-level caps.
5. **Access** — toggle between enrollment-wide and group-scoped grants.

Once saved, the model appears immediately in all AIP model selectors enrollment-wide (subject to group scoping if configured).

---

## Worked example

**Scenario:** A financial-services team has a proprietary fine-tuned GPT-4-class model hosted on their Azure OpenAI private endpoint. They want Foundry developers to use it in AIP Chatbot Studio without exposing the API key.

1. **Data Connection:** The enrollment admin creates a new REST API source pointing to `https://my-company.openai.azure.com` with the Azure API key stored as a Foundry secret.
2. **Register:** In Control Panel → AIP settings → Registered models, they click <span style="color:#2D72D2"><b>Register a model</b></span>, select the source, enter provider = `Azure OpenAI (Private)`, model name = `gpt4-finance-ft-v3`, endpoint path = `/openai/deployments/gpt4-finance-ft-v3/chat/completions?api-version=2024-02-01`, tick tool calling and structured outputs, and set enrollment TPM = 200 000.
3. **Access grant:** They enable the model for the `foundry-developers` group only.
4. **Builder use:** A developer opens AIP Chatbot Studio, creates a new chatbot, and sees `gpt4-finance-ft-v3 (Azure OpenAI (Private))` in the model picker alongside Palantir-managed models. They select it and configure their system prompt.
5. **Runtime:** When the chatbot serves a request, Foundry's inference gateway authenticates against the Azure endpoint using the stored secret — the developer never sees or handles the key.
6. **Observability:** The admin visits Resource Management → AIP usage and limits to see per-minute call volume and confirm the enrollment-level cap has not been breached.

---

## Documentation map

Sub-pages and sections in the AIP Model Catalog & BYOM documentation surface:

- **AIP overview** — high-level AIP architecture and builder tools index
- **Model Catalog / Overview** — catalog application intro, access requirements
- **Model Catalog / Model types** — completion, embedding, vision distinctions
- **Model Catalog / Lifecycle stages** — Experimental → Stable → Sunset → Deprecated definitions
- **Model Catalog / Playground** — ephemeral testing UI walkthrough
- **Model Catalog / Comparison** — side-by-side evaluation UI
- **Supported LLMs** — per-provider model tables with georestriction, context-window, and capability columns
- **Bring your own model / Overview** — when to use BYOM vs. Palantir-provided models
- **Bring your own model / Register an LLM** — step-by-step registration in Control Panel
- **Bring your own model / Use registered LLM (Legacy)** — older function-interface registration path
- **Bring your own model / Register an LLM using function interfaces (Legacy)** — chat-completion function-interface quickstart
- **Administration / Bring your own model** — enrollment admin view: Control Panel config, rate limits, access governance
- **Platform overview / Supported LLMs** — cross-platform LLM availability table

---

## Official documentation

- [AIP Overview](https://www.palantir.com/docs/foundry/aip/overview)
- [AIP Model Catalog — Overview](https://www.palantir.com/docs/foundry/model-catalog/overview)
- [Bring Your Own Model — AIP](https://www.palantir.com/docs/foundry/aip/bring-your-own-model)
- [Bring Your Own Model — Administration](https://www.palantir.com/docs/foundry/administration/bring-your-own-model)
- [Supported LLMs](https://www.palantir.com/docs/foundry/aip/supported-llms)
