# AIP Evals

> A structured testing framework inside Palantir Foundry that lets you measure, compare, and improve the quality of LLM-backed Logic functions and AI agents before putting them into production.

## What it is

AIP Evals is a dedicated evaluation environment within Foundry's AI Platform (AIP) for systematically testing AIP Logic functions, AIP Chatbot (Agent) functions, and code-authored functions. It exists because large language models are non-deterministic — the same prompt can produce different outputs on each call — which makes traditional pass/fail unit tests insufficient. AIP Evals addresses this by defining **evaluation suites** with structured test cases and configurable graders, then letting you run those suites repeatedly and compare results across runs, model versions, or prompt variants.

## When to use it

- Your AIP Logic function or agent involves LLM calls and you need confidence before publishing it to production users.
- You have changed a prompt, switched models, or refactored a Logic function and want to measure whether quality improved or regressed.
- You want to run systematic experiments comparing multiple models or parameter combinations on the same task.
- You need to validate that a function correctly creates, edits, or deletes Ontology objects (using Ontology simulation to protect live data).
- You are onboarding a new LLM-backed workflow and want a baseline metric scorecard.

**When NOT to use it:** For purely deterministic (non-LLM) TypeScript or Python functions, standard unit tests in a Code Repository are simpler and faster. AIP Evals is most valuable where stochastic output quality needs human-readable or rubric-based grading.

## Key concepts & terminology

- **Evaluation suite** — The top-level container: holds test cases, the target function(s) under test, and the evaluation functions (graders) that score each output.
- **Target function** — The AIP Logic function, AIP Chatbot function, or code-authored function being evaluated. A single suite can hold multiple target functions so you can compare them side-by-side.
- **Test case** — One row in the suite: a set of named inputs and expected output values that get fed into the target function during a run.
- **Evaluation function (grader/evaluator)** — A function that compares the actual output of the target function to the expected output and returns a Boolean or numeric metric. Can be built-in, marketplace-sourced, or custom.
- **Metric** — The scored result produced by an evaluation function for each test case. Metrics are aggregated across the whole run to give overall pass rates or scores.
- **Run** — One execution of an evaluation suite. A run applies every test case to every target function the configured number of times.
- **Experiment** — A special run mode that performs a grid search over multiple parameter combinations (e.g., different models and prompts) and generates one run per combination for systematic comparison.
- **Ontology simulation** — An isolated copy of the Ontology used when a Logic function under test creates, edits, or deletes objects, so live production data is never mutated during evaluation.
- **AI FDE (AI Foundry Development Environment)** — An AI assistant embedded in Foundry that can automatically analyze failing test cases, identify root-cause patterns, and suggest prompt improvements.

## Core capabilities / features

**Multiple target function types**
Suites can test AIP Logic functions (accessed via the Logic sidebar), published AIP Chatbot functions, and functions from Code Repositories. Multiple targets can be added to the same suite to benchmark them against identical test cases.

**Flexible test case creation**
- *Manual*: click "Add test case," name it, and fill in input and expected-output columns.
- *Object-set import*: populate test cases from a Foundry object set — each object becomes a test case. This enables realistic production-scale testing.
- Columns are editable: add, remove, reorder, and change data types at any time.

**Rich built-in evaluator library**
19+ built-in evaluators cover:
- Exact match (boolean, string, numeric, object)
- Pattern matching (regex, keyword checker)
- Edit distance (Levenshtein)
- Range validators (numeric, temporal, string length)
- LLM-as-a-judge (scores free-text output using another LLM)
- Marketplace evaluators: **Rubric grader** (LLM-backed numeric scoring against a dynamic marking rubric) and **Contains key details** (LLM-backed check that all required facts appear in the output)

**Custom evaluation functions**
Publish a TypeScript or Python function from a Code Repository that returns Boolean or numeric values (or a struct of them) and plug it directly in as an evaluator. Required for Ontology-edit scenarios.

**Experiment mode**
Parameterize a Logic function by exposing model selection and prompt text as inputs, then enable Experiments in the run configuration. AIP Evals performs a grid search across all parameter combinations and generates one run per combination for side-by-side comparison.

**Run scoping and persistence**
- *User-scoped* (default): results visible only to you, auto-deleted after 24 hours — good for quick iteration.
- *Project-scoped* (Beta): results persist indefinitely and are visible to all project members — good for team benchmarks.

**Pass/fail objectives and comparative views**
Attach a pass threshold to each metric; AIP Evals shows a pass percentage per run and highlights differences when comparing two runs side-by-side. Individual test cases can be drilled into via the Debug View, which shows full execution traces, step-by-step Logic traces, and actual vs. expected outputs.

**AI-assisted analysis**
AI FDE can scan a run's failures, surface common root causes, and propose prompt rewrites — accessible from both the AIP Evals application and the AIP Logic interface.

## How it works / typical workflow

1. **Open AIP Evals** from the AIP Logic sidebar or from the standalone AIP Evals application in Foundry.
2. **Create an evaluation suite**: give it a name and select the target function type (Logic, Chatbot, or code-authored).
3. **Add test cases**: manually enter input/expected-output rows, or import from an object set.
4. **Add evaluation functions**: pick one or more built-in evaluators, marketplace graders (e.g., Rubric grader), or custom published functions. Configure pass thresholds if desired.
5. **Configure the run**: choose function version (saved vs. published), set iteration count (3+ recommended for LLM functions due to non-determinism), adjust parallelism, and optionally add metadata tags.
6. **Run the suite**: click "Run evaluation suite." Watch per-test-case and aggregate metrics populate in real time.
7. **Analyze results**: review the pass rate dashboard, use the Debug View to inspect failing test cases, and compare against a previous run to quantify regressions or improvements.
8. **Iterate**: adjust the prompt, swap the model, or refactor the Logic function, then re-run. Use Experiments to grid-search multiple variants at once.
9. **Publish with confidence**: once pass rates meet your threshold, publish the target function to production.

## Example

**Scenario**: A Logic function summarizes customer support tickets and extracts an urgency level (Low / Medium / High). You want to ensure the function reliably extracts urgency correctly and produces readable summaries.

1. Create an eval suite targeting the `SummarizeTicket` Logic function.
2. Add 20 test cases — each with a raw ticket as input and the expected urgency level as expected output. Import from an `SupportTicket` object set to use real production samples.
3. Add two evaluators:
   - *Exact match* on the urgency field (Boolean pass/fail).
   - *Rubric grader* on the summary text, with a rubric like: "Score 1-5: does the summary capture the core complaint and avoid hallucination?"
4. Run the suite 3 times (to account for LLM variance). Results show 85% exact-match on urgency and a mean rubric score of 3.8.
5. Tweak the prompt to emphasize urgency detection, re-run, and compare. The new run shows 93% exact-match — a measurable improvement validated before publishing.

**Snippet — custom evaluation function (TypeScript) for an Ontology edit check:**
```typescript
// Returns true if a newly created WorkOrder object has the expected priority
export function checkWorkOrderPriority(
  workOrderId: string,
  expectedPriority: string
): boolean {
  const wo = Objects.search().workOrder().filter(o => o.id.exactMatch(workOrderId)).get();
  return wo?.priority === expectedPriority;
}
```
This function is published from a Code Repository and then added as a custom evaluator in the suite.

## How it connects to the rest of Foundry

- **AIP Logic** — AIP Evals is surfaced directly in the Logic sidebar; Logic functions are the primary target. Results feed back into the iteration loop inside Logic.
- **AIP Chatbot Studio** — Published chatbot/agent functions can be added as targets, enabling end-to-end agent quality testing.
- **Code Repositories** — Code-authored functions (TypeScript/Python) can serve as both target functions and custom evaluators.
- **Ontology** — Object sets supply realistic test data; Ontology simulation isolates object mutations during evaluation runs.
- **Marketplace** — Pre-built evaluators (Rubric grader, Contains key details, ROUGE scoring) are distributed and consumed via the Foundry Marketplace.
- **AI FDE** — The in-product AI assistant reads eval results and drives iterative prompt improvements in a conversational interface.

## Tips & gotchas for learners

- **Run LLM-backed functions at least 3 times per test case.** A single run can mask variance; aggregate metrics across iterations give a reliable signal.
- **User-scoped results expire in 24 hours.** If you need a persistent benchmark, switch to project-scoped runs (currently Beta) before running.
- **Chatbot functions must be published first.** Unlike Logic functions (which can be tested in a saved/draft state), chatbot targets must go through the publish step.
- **Ontology-edit evaluators must be custom.** Built-in evaluators cannot inspect simulated Ontology changes; you must write and publish a TypeScript evaluator that queries the simulation.
- **Input column names do not need to match function parameter names exactly.** Use the mapping step in run configuration to align them.
- **Experiments multiply run time.** A grid search over 3 models x 3 prompts = 9 runs. Budget time and LLM token costs accordingly.
- **Start with a small, high-quality test case set.** 10–20 carefully chosen cases with clear expected outputs are more useful than 100 vague ones.

## Official documentation

- [AIP Evals — Overview](https://www.palantir.com/docs/foundry/aip-evals/overview)
- [AIP Evals — Evaluation suites for Logic functions (Getting Started)](https://www.palantir.com/docs/foundry/aip-evals/getting-started)
- [AIP Evals — Create an evaluation suite](https://www.palantir.com/docs/foundry/aip-evals/create-suite)
- [AIP Evals — Run an evaluation suite](https://www.palantir.com/docs/foundry/aip-evals/run-suite)
- [AIP Evals — Analyze run results](https://www.palantir.com/docs/foundry/aip-evals/analyze-run-results)
- [AIP Evals — Run experiments](https://www.palantir.com/docs/foundry/aip-evals/experiments)
- [AIP Evals — Evaluate Ontology edits](https://www.palantir.com/docs/foundry/aip-evals/ontology-edits)
- [AIP Logic — AIP Evals Overview](https://www.palantir.com/docs/foundry/logic/evaluations-overview)
- [AIP Logic — View results in metrics dashboard](https://www.palantir.com/docs/foundry/logic/evaluations-metrics-dashboard)
