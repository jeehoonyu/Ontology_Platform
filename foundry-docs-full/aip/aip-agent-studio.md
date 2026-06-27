<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · AI PLATFORM</b><br>
<span style="font-size:22px"><b>AIP Agent / Chatbot Studio</b></span><br>
<span style="color:#ABB3BF">A no-code builder for creating LLM-powered conversational assistants grounded in enterprise Ontology data and custom tools.</span>
</td></tr></table>

---

## What it is

AIP Chatbot Studio (formerly AIP Agent Studio) is the Palantir Foundry tool for building **AIP Chatbots** — interactive AI assistants that combine large language models with live Ontology data, documents, and custom tool invocations. Chatbots can be deployed inside Workshop applications, called via Foundry APIs, or published as reusable Functions across the platform. The studio enforces Palantir's platform security model throughout: the LLM is granted access only to the specific data and operations required for each task.

---

## How it works

AIP Chatbot Studio composes four runtime layers that are assembled at configure-time and executed turn-by-turn at inference time.

### 1. System prompt assembly

When a chatbot is invoked, the platform compiles a **raw system prompt** from three sources:

- The author-written **instructions** (free-text guidance for the model).
- Descriptions of every configured **tool** (name, purpose, parameter schema).
- Descriptions of every configured **application state variable** (name, type, current value).

This compiled prompt is sent as the system message to the chosen LLM. Temperature (0–1) is applied at this stage.

### 2. Retrieval-Augmented Generation (RAG)

Before each user turn reaches the model, **retrieval context** is run deterministically against the user message and any active application state. Three retrieval modes exist:

| Mode | Mechanism |
|---|---|
| **Ontology Context** | Queries Ontology object types (fixed set or semantic search); configurable property inclusion and application-state-driven filters. |
| **Document Context** | Passes full document text or performs semantic search over chunks to return the most relevant passages. |
| **Function-Backed Context** | A TypeScript function executes arbitrary retrieval logic and returns a `retrievedPrompt` string that is injected directly into the system prompt. |

Retrieved content is inserted into the system prompt context. If citations are configured, content is wrapped in XML structures that the chatbot UI renders as inline source links.

### 3. Tool invocation

During a conversation turn the LLM can decide to call one or more **tools** rather than (or before) generating a reply. Six tool types are available:

- **Action** — writes back to the Ontology (with optional user confirmation step).
- **Object Query** — reads object types with filtering, aggregation, and link traversal; the LLM constructs query inputs dynamically.
- **Function** — invokes any published Foundry Function, including AIP Logic functions.
- **Update Application Variable** — mutates the chatbot's own application state in the current session.
- **Command** — triggers operations in other Palantir applications.
- **Request Clarification** — pauses the turn and prompts the user for more information.

Two calling modes control how tools are offered to the model:

- **Prompted Tool Calling** — tool descriptions are embedded in the prompt; supports one call per turn; works with all models.
- **Native Tool Calling** — the model uses its built-in function-calling capability; supports parallel calls per turn; restricted to select Palantir-hosted models and the Action, Object Query, Function, and Update Application Variable tool types.

### 4. Session and context window management

Each conversation is a **session**. The context window presented to the LLM on each turn contains: compiled system prompt + conversation history + retrieval context injected for that turn. When accumulated tokens exceed the model's context limit a new session must be started. Session metadata, full exchange histories, and RAG context records are retrievable via the **Foundry API** (`aip-agents-v2` resources: `sessions`, `session-traces`, `get-rag-context-for-session`).

### 5. Publishing and integration

A finished chatbot can be **published as a Foundry Function**, making it callable from:

- **AIP Evals** — for systematic quality evaluation.
- **Automate** — to embed chatbot turns inside automated workflow pipelines.
- **Code Repositories** — for programmatic invocation in TypeScript/Python.
- **Workshop** — as an embedded chat widget inside any application, receiving Workshop application state as live context variables.

---

## User interface

The studio opens as a split-pane editor. The overall shell sits on <span style="color:#ABB3BF">app background `#111418`</span> with panels on <span style="color:#ABB3BF">raised surface `#1C2127`</span>.

### Main screens

**<span style="color:#8ABBFF">Edit mode</span>** — The primary authoring surface, divided into:

- <span style="color:#2D72D2">**Left sidebar**</span>: Configuration sections stacked vertically — *Model*, *Instructions*, *Information & Tools*, *Application State*, *Conversation Starters*, and *Settings* (temperature, session logging toggle).
- <span style="color:#2D72D2">**Center canvas**</span>: Live chat preview panel. Messages you send here test the chatbot in real time, showing retrieval context and tool-call traces inline.
- <span style="color:#2D72D2">**Right sidebar**</span>: Context inspector — shows the compiled system prompt, token counts, and (when a tool fires) a "View reasoning" trace of the model's decision.

**<span style="color:#8ABBFF">View mode</span>** — Renders the chatbot exactly as an end-user would see it (no config chrome). Used for acceptance testing before publishing.

**<span style="color:#8ABBFF">Monitoring tab</span>** — Time-series charts of session volume, message counts, and user feedback ratings.

**<span style="color:#8ABBFF">Usage tab</span>** — Token consumption and model cost breakdown by time range.

### What you see — status indicators

<table style="border-collapse:collapse;background:#1C2127">
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#238551"><b>● Published</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF">Chatbot is live and reachable via API/Workshop</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#C87619"><b>● Draft / Unsaved</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF">Changes exist that have not been saved or published</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#CD4246"><b>● Error</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF">Tool invocation or retrieval step returned an error</td>
</tr>
<tr>
  <td style="padding:8px 12px"><span style="color:#2D72D2"><b>● Thinking / Calling tool</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF">Model is mid-turn; tool call or retrieval in progress</td>
</tr>
</table>

### Key interactions

- Press `/` inside the Instructions editor to insert a reference to a configured tool or application state variable.
- Use `CMD+J` / `CTRL+J` to open AIP Chatbot Studio from anywhere in the platform via quick search.
- **Save** accepts an optional version description; versions are browsable in the version history drawer.
- **Publish** deploys the current saved version; a secondary checkbox optionally publishes as a Function simultaneously.

---

## Worked example

**Scenario**: A field-operations team needs a chatbot that answers questions about active work orders and can mark a work order as complete.

1. **Create** a new AIP Chatbot named "Work Order Assistant" from *Files → + New → AIP Chatbot*.
2. **Select model** — choose the GPT-4o variant enabled on the enrollment.
3. **Add Object Query tool** — target the `WorkOrder` Ontology object type; expose properties `status`, `assignee`, `location`, `priority`; allow filtering and link traversal to related `Asset` objects.
4. **Add Action tool** — configure an Ontology edit that sets `WorkOrder.status = "Completed"`; enable the *require user confirmation* toggle so the chatbot asks "Mark WO-4821 as complete?" before writing.
5. **Write instructions**: "You are a work order assistant. Use the Work Order Query tool to look up orders by ID, status, or location. Use the Complete Work Order action only after confirming with the user."
6. **Add Conversation Starter**: "Show me all open work orders assigned to me."
7. **Test in Edit mode** — send "What open work orders do I have in Site B?" — observe the Object Query tool fire, see retrieved objects appear in the reasoning panel, verify the reply cites correct data.
8. **Publish** — embed the chatbot in a Workshop application by dropping in the Chatbot widget and binding the `currentUser` application variable to filter results automatically.

---

## Documentation map

- **Overview** — `agent-studio/overview` / `chatbot-studio/overview`
- **Core concepts** — context window, application state, retrieval, tools
- **Getting started** — create, configure, save, publish a chatbot
- **Application state** — dynamic variables in prompts
- **Retrieval context**
  - Context types (Ontology, Document, Function-backed)
  - Citations
- **Tools**
  - Overview (all six tool types)
  - Action tool
  - Object Query tool
  - Function tool
  - Update Application Variable tool
  - Command tool
  - Request Clarification tool
- **Session logging**
- **Foundry APIs** — `aip-agents-v2` REST resources: sessions, session traces, RAG context
- **API Reference** — `Get Session`, `Get Content`, `Get RAG Context For Session`, `Get Session Trace`

---

## Official documentation

- [AIP Chatbot Studio — Overview](https://www.palantir.com/docs/foundry/agent-studio/overview)
- [AIP Chatbot Studio — Core concepts](https://www.palantir.com/docs/foundry/chatbot-studio/core-concepts)
- [AIP Chatbot Studio — Getting started](https://www.palantir.com/docs/foundry/chatbot-studio/getting-started)
- [AIP Chatbot Studio — Retrieval context types](https://www.palantir.com/docs/foundry/chatbot-studio/retrieval-context)
- [AIP Chatbot Studio — Tools overview](https://www.palantir.com/docs/foundry/chatbot-studio/tools)
- [AIP Chatbot Studio — Citations](https://www.palantir.com/docs/foundry/chatbot-studio/citations)
- [AIP Chatbot Studio — Foundry APIs](https://www.palantir.com/docs/foundry/chatbot-studio/foundry-apis)
- [AIP — Platform overview](https://www.palantir.com/docs/foundry/aip/overview)
- [API Reference — Get RAG Context For Session](https://www.palantir.com/docs/foundry/api/aip-agents-v2-resources/sessions/get-rag-context-for-session)
- [API Reference — Get Session Trace](https://www.palantir.com/docs/foundry/api/aip-agents-v2-resources/session-traces/get-session-trace)
