# AIP Logic

> A no-code visual builder for creating, testing, and deploying LLM-powered functions that read from and write to the Foundry Ontology.

## What it is

AIP Logic is a development environment inside Palantir Foundry that lets application builders construct AI-powered functions by wiring together visual blocks — no traditional programming required. It solves the problem of integrating large language models (LLMs) with live operational data safely: the LLM never touches raw data directly; instead, AIP Logic mediates every interaction through Foundry's security and permissions model. AIP Logic lives inside the AIP (Artificial Intelligence Platform) suite of tools alongside AIP Chatbot Studio, AIP Evals, and AIP Analyst.

## When to use it

- You need an LLM to read Ontology objects (e.g., work orders, incidents, assets) and produce a structured output or recommendation.
- You want an AI step inside a Workshop application — for example, a "Summarize" or "Classify" button that users click.
- You need the LLM to conditionally write back to the Ontology (e.g., update a field, create a linked object) triggered by a Foundry Action or Automation.
- You want to chain multiple AI reasoning steps (prompt chaining / chain-of-thought) without writing code.
- You need to compare model performance (GPT-4 vs GPT-3.5) on a fixed test set before releasing a change.

**When NOT to use it / alternatives:**
- For purely deterministic data transforms, use Transforms (Python/Spark) — no need for an LLM.
- For a full conversational chat interface, use **AIP Chatbot Studio** (formerly AIP Agent Studio).
- For code-heavy custom logic, write a TypeScript or Python **Function** in a Code Repository and call it from AIP Logic if an LLM step is also needed.

## Key concepts & terminology

| Term | Definition |
|---|---|
| **Logic function** | The top-level artifact produced in AIP Logic; takes typed inputs and returns a typed output or an Ontology edit. |
| **Block** | A single step in a Logic function — each block takes inputs, does one thing, and passes its output downstream. |
| **Use LLM block** | The AI-specific block; wraps a prompt, a set of tools, and an output format for one LLM call. |
| **Tool** | A capability given to the LLM inside a Use LLM block so it can query data, call functions, or apply actions. The LLM requests tool use; AIP Logic executes it under the user's permissions. |
| **Ontology** | Foundry's semantic data model of objects, properties, and links — the primary data source and write target for Logic functions. |
| **Action** | A Foundry primitive that defines how Ontology edits are made; Logic functions must be called through an Action to write to the Ontology. |
| **Function-on-Objects (FoO)** | A published Logic function invoked per-object in a Workshop table or pipeline, the same way a TypeScript/Python function would be. |
| **Debugger** | A panel inside AIP Logic that exposes the LLM's chain-of-thought, generated prompts, and individual tool call results for troubleshooting. |
| **Evaluation (Evals)** | A post-publication testing framework for validating function quality, comparing models, and tracking consistency across runs. |
| **Temperature** | An LLM configuration setting (default: 0) that controls output randomness; lower values give more deterministic results. |

## Core capabilities / features

### Six block types
1. **Use LLM** — sends a prompt to an LLM with optional tools and returns text, a structured object, or an Ontology edit decision.
2. **Apply Action** — deterministically executes a Foundry Action without an LLM; gives precise control over Ontology writes.
3. **Execute Function** — calls any existing TypeScript, Python, or other Logic function; enables reuse of existing logic.
4. **Conditionals** — if/else branching; all branches must return the same output type.
5. **Loops** — iterates over a collection; runs in parallel automatically when no Action is performed inside the loop body.
6. **Create Variable** — defines a typed variable (string, integer, boolean, object, array, timestamp, etc.) for use in later blocks.

### Tools available inside a Use LLM block
- **Query Objects** — lets the LLM read specific Ontology object types and properties; configure return limits to control token usage.
- **Apply Actions** — lets the LLM request an Ontology write; the actual edit runs under the calling user's permissions.
- **Call Function** — lets the LLM invoke a code-defined or Logic function (including other AIP Logic functions).
- **Calculator** — performs precise mathematical calculations, preventing LLM arithmetic errors.

### Security model
LLMs never have direct data access. Every tool call is intercepted and executed by AIP Logic using the invoking user's Foundry permissions, so data governance and row-level security are automatically enforced.

### Prompt engineering support
The interface guides builders to lead prompts with a task overview, then specify available data and how tools should be used. Few-shot examples can be embedded in the prompt to improve model performance.

### Testing and evaluation
- **Unit tests** — save specific input/output pairs as test cases; run them after any prompt change.
- **Debugger** — inspect the full chain-of-thought, generated prompts, and tool responses in real time during a test run.
- **AIP Evals** — after publishing, run structured evaluations to compare models or validate consistency across many inputs.

### Automation integration
AIP Logic functions can be triggered automatically via Foundry Automations, enabling Ontology edits or staged human review without manual action.

## How it works / typical workflow

1. **Open AIP Logic** — navigate via workspace search (`Ctrl+J` / `Cmd+J`) or create a new Logic file inside a project folder (home folders are not supported).
2. **Define inputs** — specify input types such as Ontology object, string, array, or timestamp that the function will receive when called.
3. **Add blocks** — drag in a Use LLM block; write a prompt and add tools (e.g., Query Objects to read related assets, Apply Actions to write results back).
4. **Chain blocks** — add further blocks (conditionals, loops, additional LLM steps) where each block can reference outputs from all prior blocks.
5. **Define the output** — set the final output type (string, structured Struct, Ontology object, or Ontology edit).
6. **Debug** — run the function with sample inputs; inspect the Debugger panel to review chain-of-thought and tool call results.
7. **Save unit tests** — capture good input/output pairs as regression tests using the unit tests icon.
8. **Publish** — click Publish to make the Logic function available across the platform.
9. **Wire into Workshop or Actions** — attach the published function to a Workshop button/module, an Action, or an Automation. For Ontology writes, the function must be invoked through an Action.
10. **Monitor with Evals** — after deployment, run AIP Evals to validate quality and compare models before releasing prompt changes.

## Example

**Scenario:** A field operations team wants a button in Workshop that reads an equipment asset from the Ontology and generates a plain-language maintenance summary.

Logic function setup:
- **Input:** `asset` (Ontology object of type `Equipment`)
- **Block 1 — Use LLM:**
  - Prompt: *"You are a maintenance analyst. Summarize the maintenance history and flag any overdue tasks for the equipment described below."*
  - Tool: **Query Objects** configured to read `MaintenanceRecord` objects linked to the input `asset`
  - Output: string (the summary)
- **Output:** the string from Block 1

In Workshop, a button calls this Logic function with the selected row's `Equipment` object as the input, then displays the returned string in a text widget. No code is written anywhere in this flow.

## How it connects to the rest of Foundry

| Related feature | Relationship |
|---|---|
| **Ontology** | Primary data source and write target; object types, properties, and links are the inputs and outputs of Logic functions. |
| **Actions** | Required intermediary for any Ontology writes; a Logic function is called *through* an Action to make edits. |
| **Workshop** | The primary UI layer where Logic functions are surfaced to end users via buttons, modules, and panels. |
| **Automations** | Can trigger Logic functions on a schedule or on Ontology events, enabling fully automated AI pipelines. |
| **Functions (TypeScript/Python)** | Can be called from inside a Logic function via the Execute Function block or the Call Function tool, allowing code logic to be mixed with AI steps. |
| **AIP Chatbot Studio** | A companion AIP tool for building conversational agents; Logic functions can be used as tools within a chatbot. |
| **AIP Evals** | The evaluation framework for Logic functions; validates quality and enables model comparisons after publishing. |

## Tips & gotchas for learners

- **5-minute execution limit in production:** Functions run without time limits in the Debugger, but calls from Workshop or the API time out after 5 minutes. Test with realistic data volumes before going live.
- **Token budget matters:** Every tool response counts toward the model's context limit. Limit the properties returned by Query Objects and set sensible object return caps to stay within limits. Switch to a 32k model if you hit limits frequently.
- **Start with one block:** Build and test a single Use LLM block before splitting into multiple blocks. Once results are inconsistent or you hit context limits, then split into separate blocks — each gets its own context window.
- **Temperature defaults to 0:** This makes outputs deterministic and reproducible, which is usually what you want for operational workflows. Raise it only when creative variation is acceptable.
- **Logic files must live in a project folder:** You cannot save a Logic file in your personal home folder. Create or use an existing project first.
- **Ontology writes always need an Action:** A Logic function cannot write to the Ontology on its own — it must be called through a Foundry Action. This is by design to keep the audit trail and permission model intact.
- **Use few-shot examples for reliability:** Adding 5–10 example inputs and their expected outputs directly in the prompt dramatically improves LLM consistency for structured extraction tasks.
- **Loops parallelize automatically:** If a loop contains no Action calls, AIP Logic runs iterations in parallel for performance. Add an Action inside a loop only when ordering matters.

## Official documentation

- [AIP Logic — Overview](https://www.palantir.com/docs/foundry/logic/overview)
- [AIP Logic — Getting Started](https://www.palantir.com/docs/foundry/logic/getting-started)
- [AIP Logic — Core Concepts](https://www.palantir.com/docs/foundry/logic/core-concepts)
- [AIP Logic — Blocks](https://www.palantir.com/docs/foundry/logic/blocks)
- [AIP Logic — FAQ](https://www.palantir.com/docs/foundry/logic/faq)
- [AIP — Overview](https://www.palantir.com/docs/foundry/aip/overview)
