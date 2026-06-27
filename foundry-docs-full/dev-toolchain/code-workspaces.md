<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DEV TOOLCHAIN</b><br>
<span style="font-size:22px"><b>Code Workspaces</b></span><br>
<span style="color:#ABB3BF">Fully-managed, browser-accessible JupyterLab, RStudio Workbench, and VS Code IDEs running on Foundry infrastructure with built-in data governance.</span>
</td></tr></table>

## What it is

Code Workspaces brings three industry-standard IDEs — **JupyterLab**, **RStudio Workbench**, and **VS Code** — directly into Palantir Foundry as ephemeral, cloud-hosted containers. Each workspace is backed by a Code Repository (git), inherits Foundry's permission and data-marking model, and can read or write Foundry datasets and Ontology objects without any manual credential configuration. The feature is designed for interactive data science, ML model development, and application prototyping where single-node computation is sufficient; for large-scale distributed workloads, Pipeline Builder or Code Repositories with Spark transforms are preferred.

---

## How it works

### 1. Workspace creation and backing repository

When you create a workspace you specify:
- **IDE type** — JupyterLab, RStudio Workbench, or VS Code.
- **Backing Code Repository** — an existing or new Foundry git repository. The workspace is a live view of one branch of that repository; the branch selector is always visible at the top of the IDE.
- **Environment profile** — a named compute profile (CPU cores, RAM). Default limits are 8 CPUs and 64 GB RAM; larger profiles incur higher compute costs.
- **Network policies** (optional, admin-enabled) — attached to allow or restrict outbound API calls to external systems.

### 2. Container lifecycle and auto-shutdown

Launching the workspace spins up a single-node container on Palantir infrastructure. An **auto-shutdown timer** (default 30 minutes, configurable up to 6 hours) terminates the container after inactivity to control cost. A session lasts at most 24 hours total before it must be relaunched.

### 3. Data access — reading

The workspace surfaces Foundry data through two mechanisms:

- **Data tab / alias registration** — A user navigates to the <span style="color:#8ABBFF">Data</span> tab and adds a dataset (tabular dataset, non-tabular dataset, Iceberg table, virtual table, or restricted view). Foundry stores the dataset RID → alias mapping in a hidden `.foundry` folder inside the repository. The alias is then usable in code.
- **In-code SDK calls**:
  - Python/Jupyter: `foundry.transforms.Dataset("<alias>").read_table(format="pandas")` — also supports PyArrow and Polars; `.files()` and `.where()` for filtered reads; `containers_sql.FoundrySdkSqlExecutor` for SQL.
  - R/RStudio: `datasets.read_table()`, `datasets.list_files()`, with `dplyr` filter integration and `reticulate` for Python interoperability.

Row and column filters are applied **before data transfer** so only the needed slice is loaded into the container's memory.

### 4. Data access — writing

Writes are issued as **transactions** against an output dataset:
- `SNAPSHOT` transactions replace the dataset's latest snapshot with new tabular data.
- `UPDATE` transactions append or replace individual files.

While working interactively, writes land on a **code-workspace-sandbox branch**. When the notebook or script is promoted to a production transform (via the <span style="color:#8ABBFF">Transform/Build</span> integration), the same write logic runs as a single committed transaction, and the output dataset appears in Foundry's lineage graph with the workspace repository as the upstream node.

### 5. Persistence and checkpoints

Two saving mechanisms exist:
- **Code Sync (manual)** — committing via the Source Control panel pushes changes to the backing git repository. This is the canonical, permanent save.
- **Checkpoints (automatic)** — data checkpoints are written every 10 minutes; a code checkpoint captures uncommitted changes just before container shutdown, so no work is lost between syncs.

Files should be placed in `data-checkpoint/` (persisted across sessions) or `data-tmp/` (discarded at shutdown) to manage performance.

### 6. Environment and packages

- **JupyterLab**: packages installed with `maestro env conda install <pkg>` or `maestro env pip install <pkg>`. Changes are tracked in the environment profile attached to the repository.
- **RStudio**: `renv::install()` for CRAN; `renv::install("bioc::<pkg>")` for Bioconductor. The `renv.lock` file is committed to the repository.
- **VS Code**: the **Palantir extension** handles automatic environment initialization at startup for each supported workflow type (Python transforms, OSDK React apps, Compute Modules, Python libraries), including Node/npm setup for front-end work.

### 7. Git and collaboration

Code Workspaces are backed entirely by Code Repositories infrastructure — branching, merging, commit history, and pull requests all work through standard git semantics. Multiple users can open the same workspace on different branches and merge via pull requests. The <span style="color:#8ABBFF">VS Code variant</span> additionally provides OAuth-preconfigured git remotes, continuous integration hooks, and live-reload for development servers.

### 8. Security and governance

Foundry's dataset-level permission markings propagate automatically into the container: a user who lacks access to a dataset cannot load it into the workspace even if they have the alias. The workspace inherits all markings from every loaded dataset; any output dataset written from that workspace carries the union of those markings. The entire feature is built to FedRAMP and GxP compliance standards.

---

## User interface

### Overall layout

Opening Code Workspaces from the Foundry navigation bar presents a **project explorer** panel on the left and a **workspace launcher** in the main area. Once a workspace is launched, the full third-party IDE (JupyterLab, RStudio, or VS Code) occupies the browser tab — Foundry UI chrome is minimal and confined to a thin top bar.

### Key panels and controls

<table>
<tr style="background:#252A31;color:#F6F7F9">
<th style="padding:8px 12px;border:1px solid #383E47;text-align:left">UI Element</th>
<th style="padding:8px 12px;border:1px solid #383E47;text-align:left">Location</th>
<th style="padding:8px 12px;border:1px solid #383E47;text-align:left">Purpose</th>
</tr>
<tr style="background:#1C2127;color:#F6F7F9">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>General tab</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Workspace home</td>
<td style="padding:8px 12px;border:1px solid #383E47">Select folder, IDE type, backing repository, and compute profile; launch the container</td>
</tr>
<tr style="background:#1C2127;color:#F6F7F9">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Data tab</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Workspace home</td>
<td style="padding:8px 12px;border:1px solid #383E47">Add / Remove dataset aliases; "Add > Read data" for Foundry sources; "Upload data" for external files</td>
</tr>
<tr style="background:#1C2127;color:#F6F7F9">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Gear icon (Advanced)</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Workspace settings</td>
<td style="padding:8px 12px;border:1px solid #383E47">Set auto-shutdown timer (30 min–6 hr), compute resources, network policies</td>
</tr>
<tr style="background:#1C2127;color:#F6F7F9">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Branch selector</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Top bar (in-IDE)</td>
<td style="padding:8px 12px;border:1px solid #383E47">Create, switch, or merge branches in the backing repository without leaving the IDE</td>
</tr>
<tr style="background:#1C2127;color:#F6F7F9">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Source Control panel</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">IDE sidebar</td>
<td style="padding:8px 12px;border:1px solid #383E47">"Sync changes" commits and pushes to the backing repo; equivalent to git commit + push</td>
</tr>
<tr style="background:#1C2127;color:#F6F7F9">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Open in VS Code button</b></span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Repository header</td>
<td style="padding:8px 12px;border:1px solid #383E47">Launches a VS Code workspace from a supported repository; Palantir extension auto-configures the environment</td>
</tr>
</table>

### Workspace status indicators

<span style="color:#238551"><b>● Running</b></span> — container is active and accepting connections  
<span style="color:#C87619"><b>● Starting</b></span> — container is being provisioned  
<span style="color:#CD4246"><b>● Stopped / Error</b></span> — container shut down (auto-shutdown or failure)  
<span style="color:#2D72D2"><b>● Sync / Build</b></span> — code sync or transform build in progress  

### Permissions required

- <span style="color:#ABB3BF">**Viewer**</span> — can launch and use an existing workspace.
- <span style="color:#8ABBFF">**Editor / Owner**</span> — can modify workspace settings, create branches, change compute profile.

---

## Worked example

**Goal:** Train a scikit-learn model on a Foundry dataset and publish predictions as a new dataset.

1. Open <span style="color:#8ABBFF">Code Workspaces</span> and create a new **JupyterLab** workspace backed by a new repository named `fraud-model`. Choose the `Large (8 CPU / 64 GB)` compute profile.
2. On the <span style="color:#8ABBFF">Data tab</span>, click **Add > Read data** and select the `transactions_clean` dataset. Assign alias `transactions`. Click **Add > Read data** again, select the output dataset `fraud_predictions`, assign alias `predictions`.
3. In the notebook, run:
   ```python
   from foundry.transforms import Dataset
   import pandas as pd
   from sklearn.ensemble import RandomForestClassifier

   df = Dataset("transactions").read_table(format="pandas")
   X, y = df.drop("is_fraud", axis=1), df["is_fraud"]
   model = RandomForestClassifier(n_estimators=100).fit(X, y)

   results = pd.DataFrame({"id": df["id"], "score": model.predict_proba(X)[:,1]})
   Dataset("predictions").write_table(results)
   ```
4. Click **Sync changes** in the Source Control panel to commit the notebook to the `fraud-model` repository.
5. From the repository view, click **Publish as transform** — Foundry wraps the notebook as a scheduled transform. The `fraud_predictions` dataset now shows `fraud-model` as its upstream node in the lineage graph, and can be built on a schedule or triggered downstream.

---

## Documentation map

- **Overview** — what Code Workspaces is and when to use it vs. Pipeline Builder / Code Repositories
- **Getting started** — creating a workspace, permissions, launching JupyterLab and RStudio
- **Interact with data** — dataset aliases, read/write APIs for Python and R, filtering, transaction types
- **Interact with external systems** — network policies, outbound API calls
- **Interact with the Ontology** — reading and writing Ontology objects, OSDK usage
- **Model training** — creating model assets, tracking with modeling objectives
- **JupyterLab** — JupyterLab-specific workflows, package installation via `maestro`
- **RStudio** — RStudio-specific workflows, `renv` package management, Shiny application development
- **VS Code workspaces** — VS Code integration, Palantir extension, supported workflow types (Python transforms, OSDK React apps, Compute Modules, Python libraries)
- **VS Code · Benefits** — comparison table: VS Code Workspaces vs. Code Repositories vs. Local Palantir Extension
- **Security** — markings propagation, FedRAMP/GxP compliance
- **Compute usage** — monitoring and controlling compute spend per workspace
- **FAQ** — common questions on persistence, branching, and compute
- **Troubleshooting** — container startup failures, package conflicts, data access errors

---

## Official documentation

- [Code Workspaces — Overview](https://www.palantir.com/docs/foundry/code-workspaces/overview)
- [Code Workspaces — Getting started](https://www.palantir.com/docs/foundry/code-workspaces/getting-started)
- [Code Workspaces — Interact with data](https://www.palantir.com/docs/foundry/code-workspaces/data)
- [Code Workspaces — Interact with external systems](https://www.palantir.com/docs/foundry/code-workspaces/external-systems)
- [Code Workspaces — Compute usage](https://www.palantir.com/docs/foundry/code-workspaces/compute-usage)
- [Code Workspaces — FAQ](https://www.palantir.com/docs/foundry/code-workspaces/code-workspaces-faq)
- [VS Code workspaces — Overview](https://www.palantir.com/docs/foundry/vs-code/overview)
- [VS Code workspaces — Benefits](https://www.palantir.com/docs/foundry/vs-code/benefits)
- [Dev Toolchain — Overview](https://www.palantir.com/docs/foundry/dev-toolchain/overview)
