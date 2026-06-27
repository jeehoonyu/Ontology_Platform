<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DEV TOOLCHAIN</b><br>
<span style="font-size:22px"><b>Code Repositories</b></span><br>
<span style="color:#ABB3BF">A web-based IDE and Git-backed version control environment for authoring, testing, and publishing production data transformation pipelines on Foundry.</span>
</td></tr></table>

## What it is

Code Repositories is Palantir Foundry's primary environment for writing production-grade data pipelines and Functions. It provides a full browser-based IDE layered on top of a Git repository, giving data engineers all common version-control operations (branching, committing, pull requests, tags) alongside deep platform integration: live transform previews, a runtime debugger, unit testing, and artifact publishing. It is the recommended tool when pipelines require governance gates such as code review, audit history, or incremental compute optimization.

## How it works

### Repository types

Every Code Repository is one of two flavors:

- **Transforms repository** — hosts data transformation logic (Python, Python/Spark, Java, SQL, R, or containerized sidecar). Transforms read from Foundry datasets and write to output datasets, virtual tables, media sets, or Ontology objects.
- **Functions repository** — hosts TypeScript or Python business logic that executes with low latency in an operational context, with native access to Foundry Ontology objects for live queries.

### End-to-end mechanics

1. **Create a repository.** A repository is a Foundry object (stored in the resource tree) backed by a hosted Git remote. On creation you pick a repository type and a default branch name. The system provisions the remote and scaffolds a starter project (build system, dependency manifest, and a sample transform file).

2. **Branch and edit.** You create a feature branch off `main`. The in-browser editor (Monaco-based, with IntelliSense, linting, and error underlining) opens transform files. Each transform file contains one or more `@transform` / `@transform_df` decorated Python functions (or equivalent in SQL/Java), declaring their input and output datasets by Foundry dataset RID or alias.

3. **Preview transforms.** Without merging, you trigger a **local preview** build on a subset of the input data. Foundry spins up a transient Spark compute session (sized by the active Spark profile), executes the transform against a data sample, and surfaces the resulting schema and row preview in the editor panel. This validates logic before any production dataset is written.

4. **Debug transforms.** When a preview or scheduled build fails, the **runtime debugger** attaches to the Spark executor. You can inspect logs, examine stack traces, and in supported configurations step through execution to identify schema mismatches, null-handling errors, or logic faults.

5. **Write unit tests.** Test files sit alongside transform files. The test runner executes on synthetic or sampled datasets within the repository's isolated environment, and results appear in a dedicated test panel. Checks can be enforced as merge gates via branch protection rules.

6. **Impact analysis.** Before merging a branch, you can run **impact analysis**, which traverses the downstream data lineage graph to show every dataset, pipeline, and application that will be affected by the changed outputs. This surfaces blast radius before code lands in production.

7. **Open a pull request and merge.** Pull requests are created inside the Code Repositories UI. Reviewers comment inline on diffs. Branch protection rules can require a minimum number of approvals, passing checks, or both before merge is allowed. On merge, Foundry records the commit in the audit log and triggers any downstream schedules that depend on the repository's output datasets.

8. **Incremental compute.** For Python/Spark transforms, Foundry tracks which input dataset partitions have changed since the last successful build. Only changed partitions are re-processed, reducing compute cost on large daily pipelines.

9. **Artifact publishing.** Reusable Python libraries authored inside a repository can be **published as artifacts** to a Foundry-managed artifact repository (a private PyPI-compatible index). Other repositories declare a dependency on the published package version, and Foundry resolves it at build time. Versioned artifacts can be recalled to roll back a dependency.

10. **Ontology imports.** Functions repositories can import Ontology object types directly into the code context, giving typed access to live object data without manually constructing dataset queries.

## User interface

### Overall layout

The Code Repositories application opens to a three-column shell:

| Zone | Description |
|---|---|
| <span style="color:#8ABBFF">**Left sidebar**</span> | File explorer tree (all files in the repository), branch switcher at the top, search-in-files, and quick-access shortcuts to tests and checks. |
| <span style="color:#8ABBFF">**Center editor**</span> | Monaco code editor with syntax highlighting, IntelliSense autocomplete, inline error squiggles, and a diff view when reviewing pull request changes. |
| <span style="color:#8ABBFF">**Right panel**</span> | Context-sensitive: shows transform preview results, schema inspector, test results, or impact analysis output depending on the active action. |

A persistent <span style="color:#2D72D2">**top toolbar**</span> holds the repository name, the active branch name, a **Preview** button, a **Build** button, and a pull-request / merge menu.

### Key screens

**Repository home** (panel background <span style="color:#ABB3BF">`#1C2127`</span>) — shows recent commits, open pull requests, and a summary of the last scheduled build status.

**Branch settings** — configure branch protection rules, required reviewers, and required checks. Protected branches show a <span style="color:#C87619"><b>● locked</b></span> badge.

**Build & compute panel** — displays live Spark job progress, stage DAG, and per-stage timing. Build states are rendered as:

<span style="color:#238551"><b>● success</b></span> · <span style="color:#C87619"><b>● running / stale</b></span> · <span style="color:#CD4246"><b>● failed</b></span> · <span style="color:#2D72D2"><b>● queued</b></span>

**Preview panel** — a tabular view of sampled output rows with column types, null counts, and a row count badge. A <span style="color:#2D72D2"><b>Refresh preview</b></span> button re-runs the sample build.

**Impact analysis view** — a directed graph showing downstream datasets and pipelines, with nodes colored by staleness risk.

**Artifact repository navigator** — lists published package versions with publish date, publisher, and a <span style="color:#CD4246"><b>Recall</b></span> action to deprecate a version.

**Compute Usage** — a time-series chart of Spark core-hours consumed by this repository, broken down by branch and build type.

## Worked example

**Goal:** add a new cleaned output dataset from a raw events table.

1. Open the repository `analytics-pipelines` and create branch `feature/clean-events`.
2. In the file explorer, create `transforms/clean_events.py`. Import `@transform_df` from `transforms.api` and declare `input=Input("/raw/events")` and `output=Output("/clean/events")`.
3. Write a PySpark DataFrame transform that drops nulls from the `event_id` column and casts `timestamp` to `TimestampType`.
4. Click <span style="color:#2D72D2"><b>Preview</b></span>. The right panel shows a 1,000-row sample of `/clean/events` with the corrected schema. The <span style="color:#238551"><b>● success</b></span> badge confirms the logic runs without error.
5. Add a unit test in `tests/test_clean_events.py` using synthetic rows that include null `event_id` values; assert the output contains zero nulls.
6. Run **Unit tests** — all pass (<span style="color:#238551"><b>● success</b></span>).
7. Click **Impact analysis** — only two downstream datasets are affected, both non-critical.
8. Open a pull request, request review from a team lead. After approval, merge to `main`. Foundry schedules the next run of the pipeline and writes the first full build of `/clean/events` on the next trigger.

## Documentation map

- **Overview** — `/docs/foundry/code-repositories/overview/`
- **Navigation** — `/docs/foundry/code-repositories/navigation/`
- **Configure settings in Control Panel** — `/docs/foundry/code-repositories/control-panel/`
- **FAQ** — `/docs/foundry/code-repositories/faq/`
- **Transforms**
  - Create transforms — `/docs/foundry/code-repositories/create-transforms/`
  - Preview transforms — `/docs/foundry/code-repositories/preview-transforms/`
  - Debug transforms — `/docs/foundry/code-repositories/debug-transforms/`
  - Use project references — `/docs/foundry/code-repositories/use-project-references/`
  - Analyze the impact of changes — `/docs/foundry/code-repositories/analyze-impact/`
  - Unit tests
  - Pin Spark modules in-platform
  - Libraries
  - AIP features
  - Add dataset transformation to Marketplace product
- **Artifact Repositories**
  - Overview, Navigation, Create, Delete, Publish, Recall, Manage permissions
- **Advanced Workflows**
  - Custom checks
  - Prepare datasets for download
- **Administration**
  - Branch settings
  - Repository settings
  - Repository upgrades
  - Spark profiles
  - Artifact settings
  - Ontology imports
  - Advanced repository settings
  - Compute Usage

## Official documentation

- [Code Repositories — Overview](https://www.palantir.com/docs/foundry/code-repositories/overview)
- [Code Repositories — Navigation](https://www.palantir.com/docs/foundry/code-repositories/navigation)
- [Code Repositories — Documentation index](https://www.palantir.com/docs/foundry/code-repositories/readme)
- [Code Repositories — FAQ](https://www.palantir.com/docs/foundry/code-repositories/faq)
- [Comparison: Code Repositories vs. Code Workbook vs. Code Workspaces](https://www.palantir.com/docs/foundry/code-workbook/code-products-comparison)
