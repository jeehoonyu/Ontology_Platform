<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · AI PLATFORM</b><br>
<span style="font-size:22px"><b>AIP Evals</b></span><br>
<span style="color:#ABB3BF">A systematic evaluation framework for measuring, comparing, and improving the performance of LLM-backed functions before production deployment.</span>
</td></tr></table>

## What it is

AIP Evals is a testing environment built into Palantir Foundry that addresses the non-deterministic nature of large language models by providing a structured way to benchmark function outputs against expected results. It allows teams to create test suites, define measurement criteria, run controlled experiments across model and prompt variations, and track aggregate performance trends over time — all without touching live Ontology data. It integrates with AIP Logic, AIP Chatbot Studio functions, and code-authored functions authored in Code Repositories.

---

## How it works

AIP Evals is built around five interlocking objects: **evaluation suites**, **target functions**, **test cases**, **evaluators**, and **metrics**. Together they form a repeatable pipeline:

1. **Define a target function.** You nominate one or more functions (AIP Logic functions, AIP Chatbot functions, or TypeScript/Python functions published from Code Repositories) as the subjects under test. A single evaluation suite can hold multiple target functions simultaneously, enabling head-to-head comparisons.

2. **Assemble test cases.** Test cases are input/expected-output pairs. They can be created manually — useful for precise edge cases — or generated automatically from existing Foundry **object sets**, where each object in the set becomes one test case. Object-set test cases can reference linked object properties or inject static values across all rows, enabling large-scale tests grounded in real data.

3. **Attach evaluators.** Evaluators are functions that compare the actual output of the target function against the expected value in each test case. They return a **boolean** (pass/fail) or a **numeric score**. Foundry ships more than 20 built-in evaluators covering string comparisons (exact match, regex, Levenshtein distance), numeric range checks, array comparisons, object/object-set matching, and **LLM-as-a-judge** evaluation. You can also deploy custom evaluators from published Code Repository functions or AIP Logic, provided they emit at least one boolean or numeric metric.

4. **Set metric objectives.** For every metric produced by an evaluator you declare an optimization direction: boolean metrics are targeted to `true` or `false`; numeric metrics are set to maximize or minimize, with an optional threshold value. These objectives drive the visual pass/fail indicators in run results.

5. **Run the evaluation suite.** When you trigger a run, each test case input is passed to every target function. Logic functions execute inside an **isolated Ontology simulation** — a sandboxed copy of the Ontology — so any object creates, edits, or deletes made by the function under test never touch the live Ontology. Evaluators then score every output, producing a metric record per test case per run.

6. **Run experiments with grid search.** To optimize model selection or prompt wording, you parameterize your function (converting hard-coded model identifiers and prompt strings into function inputs) and enable **Experiments** in the run configuration. You specify multiple values for each parameter; Evals automatically computes the Cartesian product and executes one separate evaluation run per combination. For example, 3 model choices × 4 prompt variants = 12 runs, all launched in one operation.

7. **Analyze results.** Run outputs are collected under the **Results › Runs** tab. The **Group by** control lets you pivot the table by any column (e.g., group by model to compare aggregate pass rates across all test cases). You can pin up to 4 runs side-by-side for per-test-case comparison. Double-clicking any test case opens the **LLM trace viewer**, which shows the full execution trace, intermediate parameters, and — for LLM-judge evaluators — the judge's decision rationale.

8. **Export to a dataset.** Run results can be written to a Foundry dataset for downstream analysis in Code Repositories, Workshop dashboards, or external BI tools.

---

## User interface

AIP Evals surfaces in two contexts: as a standalone tool reachable from the AIP section of the Foundry navigation, and embedded within the **AI FDE** (Foundry Development Environment) sidebar, where it supports conversational suite creation and execution via natural-language commands.

**Overall layout**

The main AIP Evals canvas follows Foundry's dark Blueprint design language. The persistent left sidebar lists evaluation suites; the right area is a tabbed workspace.

<table style="border-collapse:collapse;width:100%;background:#1C2127;color:#F6F7F8;font-size:13px">
<thead>
<tr style="border-bottom:1px solid #383E47">
<th style="padding:8px 12px;text-align:left;color:#8ABBFF">Screen / Panel</th>
<th style="padding:8px 12px;text-align:left;color:#8ABBFF">What you see</th>
</tr>
</thead>
<tbody>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px"><span style="color:#2D72D2"><b>Suite editor</b></span></td>
<td style="padding:8px 12px">A table of test cases (rows) × evaluators (columns). Cells show expected values. The toolbar contains <b>Add test case</b>, <b>Add object set</b>, and <b>+ Add</b> (evaluator).</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px"><span style="color:#2D72D2"><b>Run configuration dialog</b></span></td>
<td style="padding:8px 12px">A modal for selecting target function version, setting iteration count, toggling <b>Experiments</b>, and specifying parameter value grids. Displays the computed total run count.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px"><span style="color:#2D72D2"><b>Results › Runs tab</b></span></td>
<td style="padding:8px 12px">A table of completed runs with aggregate metric columns, timestamps, and parameter values on hover. <b>Group by</b> selector in the toolbar. Up to 4 runs selectable for side-by-side comparison.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px"><span style="color:#2D72D2"><b>Test case comparison view</b></span></td>
<td style="padding:8px 12px">Selected runs appear as adjacent columns; each row is a test case showing the function output and evaluator score per run.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px"><span style="color:#2D72D2"><b>LLM trace viewer</b></span></td>
<td style="padding:8px 12px">A deep-drill panel showing the full execution trace: inputs, intermediate parameters, LLM calls with token counts, and final outputs. LLM-judge evaluations include the judge's reasoning.</td>
</tr>
<tr>
<td style="padding:8px 12px"><span style="color:#2D72D2"><b>Metrics dashboard</b></span></td>
<td style="padding:8px 12px">Charts and aggregate statistics across runs. Accessible via <b>View metrics dashboard</b> in the run results view or the <b>Run tests</b> tab.</td>
</tr>
</tbody>
</table>

**Status indicators used across the UI:**

<span style="color:#238551"><b>● pass</b></span> · <span style="color:#CD4246"><b>● fail</b></span> · <span style="color:#C87619"><b>● pending / in progress</b></span> · <span style="color:#2D72D2"><b>● primary action</b></span> · <span style="color:#ABB3BF">● muted / not set</span>

**Key interactions:**
- The <span style="color:#9D3F9D">purple AIP star icon</span> next to any test-case name field invokes AI-powered auto-naming.
- Clicking **Add target function** inside an open suite appends additional functions for side-by-side benchmarking.
- Evaluators sourced from the marketplace appear in a browseable gallery alongside built-in options.
- In the Runs table, hovering over an experiment run cell reveals the parameter values used for that run.

---

## Worked example

**Scenario:** A team has built an AIP Logic function `classifySupportTicket` that uses an LLM to assign a priority class (`P1`–`P4`) to incoming tickets. They want to compare GPT-4o vs. Claude Sonnet and also test two prompt phrasings before promoting to production.

1. **Create evaluation suite** named `classifySupportTicket – Evals`.
2. **Add object set test cases** from the `SupportTickets_QA` object set (200 labeled tickets). Map `ticketBody` to the function input and `expectedClass` to the expected output column.
3. **Add evaluator** → built-in **Exact match** evaluator. Map `actualClass` output to Actual value and `expectedClass` column to Expected value. Set objective to `true`.
4. **Parameterize the function**: convert the hard-coded `modelName` and `systemPrompt` variables into optional function inputs.
5. Open **Run configuration** → enable **Experiments** → define `modelName` values as `["gpt-4o", "claude-sonnet-3-5"]` and `promptVariant` values as `["concise", "detailed"]`. Total runs shown: **4**.
6. Click **Run**. Evals spins up 4 separate runs in the Ontology sandbox, each executing all 200 test cases.
7. In **Results › Runs**, group by `modelName`. Claude Sonnet shows 91 % exact-match pass rate vs. GPT-4o's 88 % across both prompt variants.
8. Select the two best runs → **Compare** → inspect the 18 test cases where the models diverged. Double-click one → **LLM trace viewer** reveals GPT-4o mislabeled ambiguous tickets as `P2` when the prompt was concise.
9. Decision: ship `claude-sonnet-3-5` with the detailed prompt. Export results to a dataset for audit lineage.

---

## Documentation map

The following sub-pages exist beneath AIP Evals in the Palantir docs:

- **Overview** — Introduction, building blocks, and integration points
- **Evaluation suites for Logic functions (Getting started)** — Guided walkthrough for first-time suite creation
- **Create an evaluation suite** — Detailed instructions for suite setup, target functions, test cases, and evaluators
- **Evaluate Ontology edits** — How to write evaluators for Logic functions that create, modify, or delete Ontology objects in the sandbox
- **Run experiments** — Grid search setup, parameterization, and experiment results analysis
- **Analyze run results** — Runs table, grouping, comparison view, and debugger
- **Write run results to a dataset** — Exporting evaluation output for downstream use
- **View results in metrics dashboard** — Aggregate charts, statistics, and trace viewer access

Legacy/cross-linked pages under `logic/evaluations-*` mirror parts of this surface for AIP Logic-specific entry points.

---

## Official documentation

- [AIP Evals · Overview](https://www.palantir.com/docs/foundry/aip-evals/overview)
- [AIP Evals · Evaluation suites for Logic functions (Getting started)](https://www.palantir.com/docs/foundry/aip-evals/getting-started)
- [AIP Evals · Create an evaluation suite](https://www.palantir.com/docs/foundry/aip-evals/create-suite)
- [AIP Evals · Evaluate Ontology edits](https://www.palantir.com/docs/foundry/aip-evals/ontology-edits)
- [AIP Evals · Run experiments](https://www.palantir.com/docs/foundry/aip-evals/experiments)
- [AIP Evals · Analyze run results](https://www.palantir.com/docs/foundry/aip-evals/analyze-run-results)
- [AIP Evals · Write run results to a dataset](https://www.palantir.com/docs/foundry/aip-evals/results-dataset)
- [AIP Evals · View results in metrics dashboard](https://www.palantir.com/docs/foundry/aip-evals/metrics-dashboard)
- [AIP · Overview](https://www.palantir.com/docs/foundry/aip/overview)
- [AIP Logic · AIP Evals · Overview (legacy path)](https://www.palantir.com/docs/foundry/logic/evaluations-overview)
