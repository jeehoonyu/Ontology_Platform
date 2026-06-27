<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DEV TOOLCHAIN</b><br>
<span style="font-size:22px"><b>Compute Modules</b></span><br>
<span style="color:#ABB3BF">Deploy serverless Docker containers on the Foundry platform to run custom code at scale, in any language, integrated with the Ontology and build system.</span>
</td></tr></table>

## What it is

Compute Modules is the Foundry mechanism for running arbitrary containerized workloads inside the platform. Developers package their code — Python, Java, TypeScript/Node.js, or any language — into Docker images, then Foundry manages scaling, scheduling, credential injection, and integration with the rest of the platform. Compute Modules are the escape hatch that lets teams bring their own models, algorithms, and third-party integrations without rewriting them as native Foundry transforms.

## How it works

Compute Modules operate on a **replica-based, poll-driven execution model**. The platform manages replicas (live container groups) and routes incoming requests or build triggers to them.

### Core building blocks

| Object | What it is |
|---|---|
| **Image** | An immutable Docker image stored in a Foundry-connected Artifact repository. Must target `linux/amd64`, run as a non-root numeric user (e.g. `USER 5000`), and expose ports only in the range 1024–65535 (excluding 8945/8946). |
| **Replica** | A live instance of the full container set. Multiple replicas run in parallel; they are fully isolated — no cross-replica networking or shared state. |
| **Entry-point container** | The container inside a replica that implements the polling client (SDK loop). It calls the platform's Job Queue endpoint at a configurable interval, picks up pending requests, executes the handler function, and posts the result back. |
| **Function** | A named, schema-defined handler registered in the UI. Takes a JSON `event` object (arbitrary inputs) and a `context` object (token, ontology RID, metadata), and returns a JSON-serializable result. |
| **Pipeline resource** | A Foundry dataset, streaming dataset, or media set wired in as an input or output for pipeline-mode modules. |

### Execution modes

**Function mode** — interactive, on-demand invocation:

1. A Workshop widget, Slate app, or OSDK call issues a request to the compute module's endpoint.
2. The platform queues the request in the Job Queue.
3. An available replica's entry-point container polls the queue, dequeues the request, and invokes the registered handler function.
4. The handler receives the `context` object (carrying `CLIENT_ID`, `CLIENT_SECRET`, `RUNTIME_HOST`, and optionally `SOURCE_CREDENTIALS` for any wired external sources) and the `event` object (the caller's input payload).
5. The result is serialized as JSON and returned through the queue to the caller.
6. Replicas scale horizontally as request volume increases; idle replicas are scaled down automatically.

**Pipeline mode** — build-system-driven, provenance-tracked transformation:

1. A Foundry pipeline schedule or manual build trigger fires.
2. The Foundry build system injects a short-lived `BUILD2_TOKEN` (bearer token) via environment variable and a `RESOURCE_ALIAS_MAP` mapping each configured alias to a dataset/stream RID and branch.
3. The compute module reads input records via the `stream-proxy` API (authenticated with the bearer token), processes them, and writes output records to the configured output resource.
4. The build system tracks data lineage for every input and output, enforcing marking controls and audit trails exactly as with native transforms.
5. The module loops (e.g., 60-second intervals) until processing completes, then exits cleanly.

### Deployment pipeline

1. Write application code using one of the open-source SDKs (`@function` decorator in Python; `ComputeModule` builder in Java; function registration in TypeScript).
2. Create a `Dockerfile` (`FROM --platform=linux/amd64 ...`), install dependencies, set `USER 5000`.
3. Publish the image to a Foundry Artifact repository via `Publish to DOCKER` or by pushing from a Code Repository tag.
4. In the compute module's <span style="color:#8ABBFF">**Configure tab**</span>, add the container referencing the repository + image digest/tag, then select **Update configuration**.
5. Start the module. Replicas launch, begin polling, and become ready to serve requests.

## User interface

Compute Modules is accessed via the Foundry application launcher. From any project folder, **+ New > Compute Module** creates a new module resource.

### Main screens

<table style="border-collapse:collapse;width:100%">
<tr style="background:#1C2127;color:#ABB3BF">
  <th style="padding:8px 12px;border:1px solid #383E47;text-align:left">Tab / Panel</th>
  <th style="padding:8px 12px;border:1px solid #383E47;text-align:left">What you do here</th>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Overview</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">See replica status, start/stop the module, view high-level health.</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Configure</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Add containers (image + repository), configure environment variables, set replica count limits, wire in external Sources, assign pipeline inputs/outputs with aliases.</td>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Functions</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Register functions manually (<b>Add function</b>) or auto-import detected functions. Define name, API name, typed inputs, and output schema.</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Query / Test</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Invoke a running function with a JSON payload and inspect the raw response inline before wiring it to a consumer.</td>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Logs</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Stream or search structured (SLS) or plaintext logs from all running replicas.</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Documentation</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">In-platform guide; also the launch point for linking to an Artifact repository for image publishing.</td>
</tr>
</table>

### Status indicators

<span style="color:#238551"><b>● Running</b></span> &nbsp;replicas healthy and polling &nbsp;·&nbsp;
<span style="color:#C87619"><b>● Starting</b></span> &nbsp;replicas launching or updating &nbsp;·&nbsp;
<span style="color:#CD4246"><b>● Failed</b></span> &nbsp;replica crash or image error &nbsp;·&nbsp;
<span style="color:#2D72D2"><b>● Stopped</b></span> &nbsp;module manually stopped

### Create function panel (Functions tab)

When you click **Add function**, a right-side drawer opens with:
- **Function name** — must match the string registered in code.
- **API name** — globally unique locator in the form `com.<namespace>.computemodules.<MyApiName>`. Changing this after consumers exist will break them.
- **Inputs** — each named input becomes a property on the JSON `event` object passed to the handler.
- **Output** — the return type schema (primitive, array, map, struct, temporal, or binary).
- **Test tab** — send a live request while the module is running to verify behavior before saving.

## Worked example

**Scenario**: a Workshop dashboard that lets analysts run a Python-based anomaly detection model against a selected dataset slice and see results immediately.

1. A data scientist creates a Code Repository of type **Python Compute Module** and writes `src/app.py`:
   ```python
   from palantir_compute_modules import function
   @function
   def detect_anomalies(context, event):
       records = event["records"]
       threshold = event.get("threshold", 3.0)
       # ... model logic ...
       return {"anomalies": [...]}
   ```
2. They tag the repository version, which builds and publishes a Docker image to the linked Artifact repository.
3. In the compute module's **Configure tab**, they select the tagged image under **Add Container** and click **Update configuration**.
4. On the **Overview** page they start the module; status flips to <span style="color:#238551"><b>● Running</b></span>.
5. On the **Functions tab** they click **Add function**, name it `detect_anomalies`, define inputs (`records: array<struct>`, `threshold: float`), set the output to `struct`, and save.
6. A Workshop builder wires a button to `com.acme.computemodules.DetectAnomalies`, passing the filtered object set as `records`. Results populate a table widget in real time.
7. Logs in the **Logs tab** show per-request timing; replicas auto-scale as more analysts open the dashboard concurrently.

## Documentation map

- `compute-modules/overview` — Capabilities, architecture overview, and use-case guidance
- `compute-modules/get-started` — Step-by-step tutorials for function-backed modules and pipeline-backed modules
- `compute-modules/concepts` — Glossary of replicas, containers, entry-point container, polling client
- `compute-modules/execution-modes` — Deep dive on Function mode vs. Pipeline mode
- `compute-modules/containers` — Dockerfile requirements, image specs, reserved environment variables, logging formats
- `compute-modules/functions` — Function registration UI, API name conventions, type schema reference
- `compute-modules/sources` — Wiring external data sources (credentials injection via `SOURCE_CREDENTIALS`)
- `compute-modules/typescript-sdk` — TypeScript/Node.js SDK reference
- `compute-modules/authoring-locally-python` — Local development workflow for Python modules
- `compute-modules/advanced-custom-client` — Writing a custom polling client without the SDK
- `compute-modules/usage` — Usage metrics and pricing model

## Official documentation

- [Compute modules — Overview](https://www.palantir.com/docs/foundry/compute-modules/overview)
- [Compute modules — Getting started](https://www.palantir.com/docs/foundry/compute-modules/get-started)
- [Compute modules — Execution modes](https://www.palantir.com/docs/foundry/compute-modules/execution-modes)
- [Compute modules — Containers](https://www.palantir.com/docs/foundry/compute-modules/containers)
- [Compute modules — Functions configuration](https://www.palantir.com/docs/foundry/compute-modules/functions)
- [Compute modules — TypeScript SDK](https://www.palantir.com/docs/foundry/compute-modules/typescript-sdk)
- [Compute modules — Sources](https://www.palantir.com/docs/foundry/compute-modules/sources)
- [Compute modules — Usage and pricing](https://www.palantir.com/docs/foundry/compute-modules/usage)
