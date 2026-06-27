<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · AI PLATFORM</b><br>
<span style="font-size:22px"><b>AIP Logic</b></span><br>
<span style="color:#ABB3BF">A no-code builder for composing, testing, and deploying LLM-powered functions that read and write to the Foundry Ontology.</span>
</td></tr></table>

## What it is

AIP Logic is Palantir Foundry's no-code development environment for creating functions powered by large language models (LLMs). A Logic function accepts structured inputs — Ontology objects, object sets, strings, and other typed values — and returns an output that is either a computed value or a direct edit to the Ontology. Functions are built by wiring together modular **blocks** in a linear chain, with each block's output available to every block that follows it. The resulting function can be triggered from Workshop applications, Actions, automations, or external systems via `curl`.

## How it works

Logic functions execute as a deterministic graph of typed blocks. The platform handles prompt assembly, LLM API calls, tool dispatch, and Ontology reads/writes; the builder only configures the blocks.

1. **Define inputs.** The function signature lists named, typed parameters: `array`, `boolean`, `date`, `double`, `float`, `integer`, `long`, `media reference`, `model`, `object`, `object list`, `object set`, `short`, `string`, `struct`, or `timestamp`. At runtime these values are resolved before any block executes.

2. **Chain blocks.** Each block receives the resolved inputs plus the outputs of every preceding block. Six block types are available:
   - **Use LLM** — the primary block. It compiles a natural-language prompt (which may reference any earlier variable), selects an LLM from the platform's model registry, optionally attaches tools, and returns a structured output. Tools available inside a Use LLM block include: *Query objects* (read Ontology object properties), *Apply actions* (write back to the Ontology via a declared Action), *Call function* (invoke any TypeScript, Python, or other Logic function), and *Calculator* (perform arithmetic). The LLM decides which tools to call, in what order, and when to produce a final response — the full chain-of-thought is captured.
   - **Apply Action** — calls an Ontology Action directly, bypassing LLM routing, for deterministic writes with precise parameter control.
   - **Execute Function** — invokes an existing TypeScript, Python, or Logic function to reuse logic already written elsewhere in Foundry.
   - **Conditionals** — `if / then / else` branching; all branches must return the same output type so the function signature remains consistent.
   - **Loops** — iterates over a collection, exposing `element` and `index` variables inside the loop body. Loops that contain no Action blocks run in parallel automatically.
   - **Create Variable** — declares a typed intermediate value (computed inline or hard-coded) that downstream blocks can reference.

3. **Resolve the output.** The final block in the chain becomes the function's return value. An output can be a typed scalar/struct (returned to the caller) or an *Ontology edit set* (staged for human review or applied automatically).

4. **Staged vs. automatic writes.** When a Logic function is backed by an Action, Ontology edits can either be queued as *staged edits* (a human reviews and approves them in a Workshop module) or applied immediately. This lets builders tune the human-in-the-loop level per use case.

5. **Publish and invoke.** Clicking **Publish** snapshots the current block graph and makes the function addressable. Published functions can be: called from Workshop modules via an Action parameter, triggered by Foundry Automate on a schedule or event, or called externally via a `curl` command copied from the **Uses** tab (not available for functions that return Ontology edits).

6. **Security model.** Every function runs under the caller's identity and is subject to Foundry's standard object-level and dataset-level ACLs. Functions cannot access data that the calling user (or the function's service account) is not permitted to read.

## User interface

AIP Logic files live inside Project folders and are opened from the workspace navigator, via quick-search (<kbd>Ctrl+J</kbd> / <kbd>Cmd+J</kbd>), or by choosing **+New → AIP Logic** in the **Files** menu. The editor is a three-panel layout:

<table style="border-collapse:collapse;width:100%;background:#1C2127;color:#fff;font-size:14px">
<thead>
<tr style="background:#252A31;border-bottom:1px solid #383E47">
  <th style="padding:8px 12px;text-align:left">Panel</th>
  <th style="padding:8px 12px;text-align:left">Position</th>
  <th style="padding:8px 12px;text-align:left">Contents</th>
</tr>
</thead>
<tbody>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#8ABBFF"><b>Configuration</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF">Left</td>
  <td style="padding:8px 12px">Inputs list, block chain (ordered cards), Outputs section. Each block card shows its type, prompt or parameters, and the output variable name it produces.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#8ABBFF"><b>Debugger</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF">Center</td>
  <td style="padding:8px 12px">After a test run: expandable block cards showing LLM chain-of-thought, tool calls made (with arguments and responses), generated prompts, and final outputs. Cards can be collapsed/cleared individually.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#8ABBFF"><b>Run Panel</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF">Right</td>
  <td style="padding:8px 12px">Input fields for test values, the <b>Run</b> button, recent runs list (for comparison), and unit-test creation. Copy <code>curl</code> requests from the <b>Uses</b> tab here.</td>
</tr>
</tbody>
</table>

**Key interactions and status indicators:**

- <span style="color:#2D72D2"><b>+ Add Block</b></span> — inserts a new block below the current one; a type picker appears.
- <span style="color:#2D72D2"><b>Publish</b></span> — snapshots and registers the function; required before it can be called from Actions.
- <span style="color:#238551"><b>● Run succeeded</b></span> — all blocks resolved; output visible in Debugger.
- <span style="color:#C87619"><b>● Stale / needs re-run</b></span> — function graph changed since last test run.
- <span style="color:#CD4246"><b>● Run failed</b></span> — at least one block errored; Debugger highlights the failing card.
- <span style="color:#9D3F9D"><b>Version History</b></span> — side-by-side diff view of any two published versions; edited, added, and removed blocks are highlighted.

The <span style="color:#8ABBFF">**Use LLM block editor**</span> occupies the full Configuration panel when open: a prompt composer at top (with `{{variable}}` interpolation), a model selector dropdown, a tools checklist (Query objects / Apply actions / Call function / Calculator), and a typed output field at the bottom.

## Worked example

**Scenario: Auto-triage incoming maintenance work orders.**

1. A Workshop form submits a new `WorkOrder` Ontology object (fields: `description`, `facility`, `priority`).
2. An Action is configured to call a published Logic function, passing the `WorkOrder` object as input.
3. Inside the Logic function:
   - **Block 1 — Use LLM** (model: `gpt-4o`): prompt reads `"Classify the following maintenance request into one of [Electrical, HVAC, Plumbing, Structural]: {{workOrder.description}}"`. Tool: *Query objects* on `Equipment` to look up asset type at the named facility. Output variable: `category` (string).
   - **Block 2 — Conditional**: if `workOrder.priority == "Critical"` then proceed to Block 3, else proceed to Block 4.
   - **Block 3 — Apply Action** (`AssignTechnician`): fills `technicianId` from a lookup and `category` from Block 1; writes back to the `WorkOrder` object immediately.
   - **Block 4 — Apply Action** (`QueueWorkOrder`): stages an Ontology edit for a supervisor to review in a Workshop approval module.
4. The builder clicks **Run** with a sample `WorkOrder`, inspects the Debugger to verify the LLM chose the correct category and the right branch executed, then clicks **Publish**.
5. The Action is wired into a Workshop module; from that point forward every new work order is automatically classified and routed without human intervention unless it is non-critical.

## Documentation map

The following sub-pages exist under AIP Logic in the Palantir docs:

- **Overview** — purpose, capabilities, security model
- **Getting started** — creating a file, configuring inputs/blocks/outputs, publishing
- **Core concepts** — Logic functions, blocks, evaluations, debugging
- **Blocks** — detailed reference for all six block types and their parameters
- **AIP Evals · Overview** — evaluation suites: target functions, test cases, evaluation functions, metrics
- **Compute usage** — how Logic function execution is metered and billed
- **FAQ** — common questions about LLM selection, Ontology permissions, versioning

## Official documentation

- [AIP Logic · Overview](https://www.palantir.com/docs/foundry/logic/overview)
- [AIP Logic · Getting started](https://www.palantir.com/docs/foundry/logic/getting-started)
- [AIP Logic · Core concepts](https://www.palantir.com/docs/foundry/logic/core-concepts)
- [AIP Logic · Blocks](https://www.palantir.com/docs/foundry/logic/blocks)
- [AIP Logic · AIP Evals Overview](https://www.palantir.com/docs/foundry/logic/evaluations-overview)
- [AIP Logic · Compute usage](https://www.palantir.com/docs/foundry/logic/compute-usage)
- [AIP Logic · FAQ](https://www.palantir.com/docs/foundry/logic/faq)
- [AIP · Overview](https://www.palantir.com/docs/foundry/aip/overview)
- [AIP · Features](https://www.palantir.com/docs/foundry/aip/aip-features)
