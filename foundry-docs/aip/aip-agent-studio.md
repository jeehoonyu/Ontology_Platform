# AIP Chatbot Studio (formerly AIP Agent Studio)

> A Foundry builder tool for creating conversational AI assistants — called AIP Chatbots — that combine LLMs with enterprise Ontology data, documents, and custom tools to automate tasks and answer questions within your organization's security perimeter.

## What it is

AIP Chatbot Studio (previously named AIP Agent Studio) is a no-code/low-code environment inside Palantir Foundry where developers and analysts build interactive AI assistants. It solves the problem of connecting a general-purpose LLM to live enterprise data — Ontology objects, document repositories, and custom business logic — without exposing more data than a user is already permitted to see. The resulting chatbots can be embedded in Workshop applications, surfaced through AIP Threads, or called programmatically via the Ontology SDK and Foundry APIs.

## When to use it

- You need a conversational assistant that can query or update Ontology objects on behalf of a user.
- You want to let non-technical users ask natural-language questions against your curated datasets.
- You are building a guided workflow where the AI walks the user through steps — collecting inputs, running Foundry Functions, and writing back results.
- You need document Q&A (PDF analysis, cross-language summarization) with grounded citations.
- You want to publish a chatbot as a reusable Function for downstream use in AIP Evals or Automate.

**When NOT to use it / alternatives:**
- For batch, fully automated pipelines with no human in the loop, use AIP Logic directly or Automate.
- For ad-hoc LLM exploration without building a shareable asset, use AIP Threads directly.
- For structured ML model inference, use the AIP Model Catalog.

## Key concepts & terminology

| Term | Definition |
|---|---|
| **AIP Chatbot** | An interactive assistant built in Chatbot Studio; previously called an AIP Agent. |
| **System prompt** | The developer-authored instructions that define the chatbot's role, tone, and how it should use its tools and context. |
| **Application state** | Dynamic variables (formerly "parameters") injected into the system prompt at runtime — e.g., the currently selected object or logged-in user. |
| **Retrieval context** | Data fetched automatically on every user message and appended to the LLM's input; the mechanism that enables RAG. |
| **RAG (Retrieval-Augmented Generation)** | A pattern where external, up-to-date data is retrieved and added to the prompt so the LLM can answer with current information rather than only training data. |
| **Tools** | External capabilities (Ontology edits, object queries, Functions, commands) the LLM can invoke at reasoning time. |
| **Context window** | The maximum number of tokens the LLM can process at once; includes system prompt, history, retrieved data, and user message. |
| **Chatbots as Functions** | A published chatbot exposed as a standard Foundry Function, callable from AIP Evals, Automate, or Code Repositories. |
| **AIP Threads** | A Foundry productivity surface where end-users start ad-hoc conversations with documents and published AIP Chatbots without any additional configuration. |
| **Vector embedding** | A numerical representation of text used to find semantically similar content during retrieval; required for semantic search on Ontology objects or document chunks. |

## Core capabilities / features

### Tool types

AIP Chatbot Studio provides six tool categories that extend the LLM beyond its training data:

- **Action** — Executes an Ontology write/edit. Can be configured to run automatically or require explicit user confirmation before the change is committed.
- **Object Query** — Grants the LLM read access to specific Ontology object types. Supports filtering, aggregation, link traversal, and property inspection. You can restrict which properties are visible to keep prompts token-efficient.
- **Function** — Calls any published Foundry Function, including AIP Logic functions, with automatic or pinned version management. This is the primary extensibility hook for custom business logic.
- **Update Application Variable** — Modifies application state variables during a conversation, enabling the chatbot to drive Workshop UI state.
- **Command** — Triggers operations in other Palantir applications via the Foundry command system.
- **Request Clarification** — Pauses tool execution and prompts the user for more information before continuing.

### Tool calling modes

- **Prompted tool calling** — Tool descriptions are embedded in the system prompt; the LLM selects and calls one tool at a time sequentially. Works with all models and all tool types.
- **Native tool calling** — Uses the model's built-in function-calling API for more efficient, parallel tool execution. Currently limited to Palantir-provided models and a subset of tool types (Action, Object Query, Function, Update Application Variable).

### Retrieval context types

Retrieval context runs automatically on every new user message:

- **Ontology context** — Fetches Ontology objects (static set or dynamically filtered via application state). Supports semantic search against a vector embedding property to surface the K most relevant objects.
- **Document context** — Passes document text to the LLM; supports either full-document injection or semantic chunk retrieval (beta) for large documents.
- **Function-backed context** — Custom TypeScript retrieval logic written in Code Repositories. The function receives the conversation `messages`, runs any combination of keyword or semantic search, and returns a `retrievedPrompt` string. Supports custom citation formatting in XML for interactive display.

### Deployment and integration

- Embeddable as a **Workshop widget** for interactive application UIs.
- Consumable via the **Ontology SDK** and Foundry platform APIs for external applications.
- Publishable as a **Foundry Function** for evaluation (AIP Evals), automation (Automate), or programmatic invocation.
- Surfaced in **AIP Threads** so end-users can start conversations without developer involvement.
- Session logging and usage monitoring are built in.

## How it works / typical workflow

1. **Open Chatbot Studio** from the workspace nav bar (Ctrl+J / Cmd+J) and select "New AIP Chatbot."
2. **Name and brand the chatbot** — add a name, description, and avatar image to white-label it for your application context.
3. **Select an LLM** from the models enabled on your Foundry enrollment.
4. **Configure retrieval context** — add Ontology object types or document sources so the chatbot has live enterprise data to draw on.
5. **Add tools** — define which Ontology edits the chatbot may perform, which object types it can query, and which Functions it can invoke.
6. **Write the system prompt** — describe the chatbot's role and instruct it on when and how to use each tool. Use `/` in the prompt editor to reference configured tools and application state variables inline.
7. **Set temperature** — use 0 for deterministic, fact-focused responses; higher values for more creative outputs.
8. **Add conversation starters and input placeholders** to guide end-users.
9. **Test in View mode** — simulate the end-user experience inside the studio.
10. **Publish** — deploys the chatbot to production; it becomes available in Workshop, AIP Threads, and via API.
11. **Monitor** — review usage metrics and user feedback in the Monitoring and Usage tabs.

## Example

**Scenario:** A logistics analyst wants a chatbot that looks up shipment Ontology objects and flags delays.

1. Create a new AIP Chatbot named "Shipment Assistant."
2. Add an **Object Query** tool targeting the `Shipment` object type, exposing properties: `shipmentId`, `status`, `estimatedArrival`, `origin`, `destination`.
3. Add a **Function** tool pointing to a published AIP Logic function `calculateDelayRisk(shipmentId)` that returns a risk score.
4. Write a system prompt: *"You are a logistics assistant. When a user asks about a shipment, use the Shipment object query tool to retrieve its details, then call calculateDelayRisk to assess whether it is at risk of delay. Summarize findings clearly."*
5. Publish and embed the chatbot widget in a Workshop dashboard alongside the shipment list view.

The analyst types: *"What is the status of shipment SHP-4421?"* — the chatbot queries the Ontology, calls the risk function, and replies with a grounded, cited summary — no SQL, no manual lookup.

## How it connects to the rest of Foundry

- **Ontology** — The foundation for all data access; Object Query and Action tools read and write Ontology objects, and all access is gated by Foundry's role-based permissions.
- **AIP Logic / Functions** — The Function tool lets chatbots invoke any published Function, enabling arbitrarily complex business logic without rewriting it inside the prompt.
- **Workshop** — Chatbots are embedded as AIP Chatbot widgets and can read/write Workshop application state variables, making them first-class citizens in interactive applications.
- **AIP Threads** — The end-user surface where published chatbots and documents are combined for ad-hoc analysis; no developer setup needed by the end-user.
- **AIP Evals** — Once published as a Function, chatbots can be systematically evaluated for quality and regression tested.
- **Automate** — Chatbots published as Functions can be scheduled or triggered in automated pipelines.
- **Code Repositories** — Function-backed retrieval context is authored in TypeScript inside Code Repos, bridging custom retrieval logic into the chatbot.
- **AIP Model Catalog** — The source of LLM choices available when configuring a chatbot.

## Tips & gotchas for learners

- **The system prompt is critical.** The LLM only knows how to use tools if you explain them clearly in the prompt. Use the `/` shortcut to reference tool names and application variables directly — this reduces ambiguity.
- **Token budget awareness.** Every retrieval context result and tool response consumes context-window tokens. If retrieval returns too many Ontology objects, responses slow down or degrade. Restrict visible properties on Object Query tools to stay efficient.
- **Prompted vs. native tool calling.** If your chatbot needs parallel tool execution (e.g., run two queries simultaneously), native tool calling is faster — but check which models on your enrollment support it. Not all models do.
- **Permissions are inherited, not overridden.** A chatbot cannot access Ontology data the calling user is not already permitted to see. This is a security feature, not a limitation to work around.
- **Test with realistic data before publishing.** The studio's View mode uses live data, so test with representative queries to catch retrieval gaps early.
- **Naming convention:** The product was renamed from "AIP Agent Studio" to "AIP Chatbot Studio." You may encounter both names in older tutorials and documentation — they refer to the same tool. Chatbots were previously called "agents."
- **Chatbots as Functions is a powerful escape hatch.** If you need to run quality evals or integrate a chatbot into a data pipeline, publish it as a Function — this unlocks the full Foundry developer toolchain.

## Official documentation

- [AIP Chatbot Studio — Overview](https://www.palantir.com/docs/foundry/chatbot-studio/overview)
- [AIP Chatbot Studio — Core Concepts](https://www.palantir.com/docs/foundry/chatbot-studio/core-concepts)
- [AIP Chatbot Studio — Getting Started](https://www.palantir.com/docs/foundry/chatbot-studio/getting-started)
- [AIP Chatbot Studio — Tools Overview](https://www.palantir.com/docs/foundry/chatbot-studio/tools)
- [AIP Chatbot Studio — Retrieval Context](https://www.palantir.com/docs/foundry/chatbot-studio/retrieval-context)
- [AIP Threads — Overview](https://www.palantir.com/docs/foundry/threads/overview)
- [AIP — Overview](https://www.palantir.com/docs/foundry/aip/overview)
- [AIP Features](https://www.palantir.com/docs/foundry/aip/aip-features)
