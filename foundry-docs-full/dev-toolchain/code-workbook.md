<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DEV TOOLCHAIN</b><br>
<span style="font-size:22px"><b>Code Workbook</b></span><br>
<span style="color:#ABB3BF">An interactive, graph-based notebook for iterative data transformation and analysis — directly inside Foundry. <em>(Legacy)</em></span>
</td></tr></table>

> **Status:** Code Workbook is in the **legacy phase**. No additional feature development is planned; full support and existing functionality remain available. New projects should consider [Code Repositories](https://www.palantir.com/docs/foundry/code-repositories/overview) for production pipelines.

---

## What it is

Code Workbook is a Foundry application that lets analysts and engineers write code (Python, SQL, R, and more) against Foundry datasets through a visual, graph-based interface. It pairs a code editor with a drag-and-drop node graph so users can see, at a glance, how data flows from raw inputs through a chain of transforms to produce curated outputs or visualizations. Its design balances low barrier to entry for less-technical users (via point-and-click templates and form-based interfaces) with the full power of a programmatic environment for engineers.

---

## How it works

### Core objects

| Object | Description |
|---|---|
| **Workbook** | The top-level resource. Stores all transforms, graph layout, environments, and branch state for one analysis project. |
| **Graph** | A directed acyclic graph (DAG) embedded inside the workbook. Each node is either an input dataset, a transform, or a derived dataset. Edges represent data dependencies. |
| **Transform** | A node that encapsulates logic. Takes one or more inputs and returns a single output DataFrame, model, or visualization. |
| **Derived dataset** | A transform whose output is persisted back to Foundry as a dataset, making it reusable by other Foundry applications. |
| **Console** | A REPL (read-evaluate-print loop) attached to the workbook. Runs ad-hoc code against any node's output without creating a permanent transform. |
| **Environment** | A Spark compute module with user-specified packages (managed via Mamba/Conda) that backs all transform execution in a workbook. |
| **Template** | A parameterized transform that exposes a form-based UI to non-technical consumers instead of a code editor. |

### End-to-end mechanics (numbered)

1. **Create a Workbook.** A user clicks **New → Code Workbook** in a Foundry Project. This instantiates a workbook resource and allocates a default Spark module for compute.

2. **Configure the Environment.** The **Environment Configuration panel** is opened to specify packages (e.g., `pandas`, `plotly`, `scikit-learn`). Foundry uses **Mamba** to resolve the full dependency tree, installs packages onto a Spark module, and caches the resolved spec file for up to 24 hours. On subsequent runs with an identical spec, the solve step is skipped entirely. If Kubernetes is enabled, a **Conda Docker** image can pre-bake the environment, eliminating installation time on each run.

3. **Import input datasets.** Clicking **Import Dataset** opens a dataset browser. The selected Foundry dataset is added to the Graph as an input node. It is not copied — Code Workbook reads directly from the Foundry dataset reference.

4. **Add transforms.** Hovering over any node reveals a blue **+** button. Clicking it opens a menu to choose a transform type:
   - **Code transform** — an editor opens for the user's chosen language (Python, SQL, R, Scala, etc.). The transform receives its upstream nodes as named variables (aliases scoped to the workbook). The return value is the output DataFrame.
   - **Template transform** — a form is presented. User fills in parameter values (datasets, column names, numbers, strings). Foundry substitutes the values into the underlying code template at run time.
   - **Manual entry transform** — a spreadsheet-style grid for small, hand-entered datasets (up to 500 rows).

5. **Execute.** Clicking **Run** on a transform (or Ctrl+clicking multiple transforms and running them together) submits the transform code to the backing Spark module. Execution output streams to the **Logs** tab in real time. Foundry can also run all downstream transforms in topological order with a single action.

6. **Inspect results.** After execution completes, the **Preview** tab shows a 50-row sample of the output. The **Visualizations** tab renders any plots produced by libraries such as Matplotlib, Plotly, or Seaborn. The **Models** tab surfaces any ML model artifacts, which are automatically written back to Foundry.

7. **Persist as a dataset.** Toggling **Save as dataset** on a transform node promotes its output to a full Foundry dataset (a *derived dataset*). This dataset lives outside the workbook and can be used by pipelines, Ontology objects, or other applications.

8. **Branch and collaborate.** Each workbook supports **branching**, analogous to Git branches. Team members open their own branches to isolate changes. Merging a branch propagates both graph changes and code edits back to the main workbook.

---

## User interface

### Overall layout

The workbook opens in a two-panel layout: a **left sidebar** and a **main canvas**.

<table style="background:#1C2127;border:1px solid #383E47;width:100%;border-collapse:collapse">
<tr style="background:#252A31">
<td style="padding:8px 12px;color:#8ABBFF;font-weight:bold;border-bottom:1px solid #383E47">Area</td>
<td style="padding:8px 12px;color:#8ABBFF;font-weight:bold;border-bottom:1px solid #383E47">What you see</td>
</tr>
<tr>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><span style="color:#fff">Left sidebar — Contents</span></td>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">In Graph mode: flat list of all transforms. In Paths mode: a mini-graph for navigation.</td>
</tr>
<tr>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><span style="color:#fff">Left sidebar — Global Code</span></td>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Editor for shared helper functions and variables available across all language-matched transforms in the workbook.</td>
</tr>
<tr>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><span style="color:#fff">Left sidebar — Console</span></td>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">REPL for ad-hoc exploration. Outputs from the console can be promoted to the graph via <b>+ Add to graph</b>.</td>
</tr>
<tr>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><span style="color:#fff">Main canvas — Graph view</span></td>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">DAG of nodes and edges. Zoom controls, multi-select (Ctrl/Cmd+Click), and right-click context menus per node.</td>
</tr>
<tr>
<td style="padding:8px 12px;color:#ABB3BF"><span style="color:#fff">Logic panel (right fly-out)</span></td>
<td style="padding:8px 12px;color:#ABB3BF">Opens when a transform is selected. Contains tabs: <b>Inputs</b>, <b>Preview</b>, <b>Visualizations</b>, <b>Logs</b>, <b>Description</b>, <b>Models</b>.</td>
</tr>
</table>

### Key interactions

- **<span style="color:#2D72D2">Import Dataset</span>** — top toolbar button that opens a Foundry dataset browser to add an input node.
- **<span style="color:#2D72D2">+ (blue dot)</span>** — hover over a node to reveal the add-downstream button; click to choose transform type.
- **<span style="color:#2D72D2">New Transform</span>** — button in the graph header for adding a free-floating (unconnected) transform.
- **<span style="color:#238551">● Run</span>** — executes the selected transform(s) on the Spark module; streaming logs appear in the Logs tab.
- **<span style="color:#C87619">● Stale</span>** — node indicator showing the transform has un-run changes or an upstream input has changed.
- **<span style="color:#CD4246">● Failed</span>** — node indicator showing the last execution produced an error; inspect Logs for stack trace.
- **Paths view** — an alternate linear view of the DAG, useful for drilling into one chain of transforms without visual clutter.
- **Full Screen Editor** — expands a single transform to fill the viewport; supports split-pane so the Preview and code are visible simultaneously.
- **Toggle View** (templates) — reveals the raw parameterized code underlying a template transform.

---

## Worked example

**Goal:** Filter the Titanic dataset to surviving female passengers and visualize their age distribution.

1. Create a folder `Code Workbook Tutorial` in your personal Foundry Project and upload `titanic_dataset.csv` there.
2. Click **New → Code Workbook**. A blank workbook opens with an empty Graph canvas.
3. Click **Import Dataset**, search for `titanic_dataset`, and select it. A grey input node appears on the Graph.
4. Hover over the `titanic_dataset` node, click the blue **+**, and choose **Python**. A code transform node labeled `transform_1` is added downstream, connected by an edge.
5. Rename the transform to `titanic_filtered` in the header text box.
6. In the Logic panel's **Inputs** tab, switch the input type from *Spark DataFrame* to *Pandas DataFrame* for easier filtering syntax.
7. In the code editor, write:
   ```python
   output_df = titanic_dataset[
       (titanic_dataset["Survived"] == 1) &
       (titanic_dataset["Sex"] == "female")
   ]
   ```
8. Click **Run**. Logs stream to the Logs tab; after completion the Preview tab shows 50 rows of results — only surviving females.
9. Add a second downstream Python transform named `age_histogram`. Import `matplotlib.pyplot` and call `plt.hist(titanic_filtered["Age"].dropna())`. The rendered histogram appears in the **Visualizations** tab.
10. On `titanic_filtered`, toggle **Save as dataset** to persist the filtered dataset to Foundry for use by other applications.

---

## Documentation map

The full Code Workbook documentation surface includes the following sections and pages beneath the tool:

- **Overview** — product summary, design goals, legacy status notice
- **Getting started** — tutorial using the Titanic dataset
- **Workbooks**
  - Workbooks overview (Graph, nodes, Paths view)
  - Supported languages (Python, SQL, R, Scala, and others)
  - Console (REPL, ad-hoc analysis, promoting results)
  - Global code (shared functions and variables)
  - Moving to production (promoting workbook outputs to datasets)
- **Transforms**
  - Transforms overview (types, inputs/outputs, execution, aliases)
- **Templates**
  - Templates overview (author vs. consumer model, parameterization, versioning)
- **Environment**
  - Environment creation overview (Mamba/Conda, Spark modules, spec files, Conda Docker, prewarming)
- **Branching** — isolation of individual changes, merging
- **Language references** — language-specific guides (Python, SQL, R, Scala)

---

## Official documentation

- [Code Workbook — Overview](https://www.palantir.com/docs/foundry/code-workbook/overview)
- [Code Workbook — Getting Started](https://www.palantir.com/docs/foundry/code-workbook/getting-started)
- [Code Workbook — Workbooks Overview](https://www.palantir.com/docs/foundry/code-workbook/workbooks-overview)
- [Code Workbook — Transforms Overview](https://www.palantir.com/docs/foundry/code-workbook/transforms-overview)
- [Code Workbook — Templates Overview](https://www.palantir.com/docs/foundry/code-workbook/templates-overview)
- [Code Workbook — Environment Creation Overview](https://www.palantir.com/docs/foundry/code-workbook/environment-creation-overview)
- [Code Workbook — Supported Languages](https://www.palantir.com/docs/foundry/code-workbook/workbooks-languages)
- [Code Workbook — Console](https://www.palantir.com/docs/foundry/code-workbook/workbooks-console)
- [Code Workbook — Moving to Production](https://www.palantir.com/docs/foundry/code-workbook/workbooks-production)
