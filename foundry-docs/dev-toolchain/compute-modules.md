# Compute Modules

> Compute Modules let you deploy your own containerized code as interactive, long-running services on Foundry compute — running custom logic, models, or dependencies that don't fit transforms or Functions.

## What it is

Sometimes you need to run arbitrary code with custom dependencies, a non-standard runtime, or as an always-available service rather than a scheduled batch job. Compute Modules package your code as a container image and run it on the Palantir platform, exposing it so the Ontology, Functions, and applications can call it. They're the escape hatch for "bring your own container" scenarios — custom inference servers, specialized libraries, or integrations that need a persistent process.

## When to use it

- You have existing code with dependencies that don't fit Foundry's managed transform/function environments.
- You need a low-latency, always-on service (e.g., a custom model server or API).
- You want to back **Functions** or Actions with containerized logic.

**When NOT to use it / alternatives:** For standard batch data processing use **transforms/Pipeline Builder**. For simple logic on objects use **Functions**. For standard ML use **Modeling** tools.

## Key concepts & terminology

- **Compute Module** — A containerized service deployed on Foundry compute.
- **Container image** — The Docker image holding your code and dependencies.
- **Interactive vs pipeline module** — Request/response service vs. data-processing job.
- **Function-backed compute module** — Exposing the module as a callable Function.
- **Endpoint** — The interface your container exposes for calls.
- **Resource configuration** — CPU/memory/replicas for the running service.

## Core capabilities / features

- **Bring your own container** — Run arbitrary code and dependencies via Docker images.
- **Interactive services** — Low-latency request/response for real-time use.
- **Integration with the Ontology** — Back Functions/Actions with module logic.
- **Custom model serving** — Host models with bespoke runtimes or frameworks.
- **Scalability** — Configure replicas and resources; scale deployments.
- **Governed execution** — Runs within Foundry's security and networking controls.

## How it works / typical workflow

1. **Build a container image** with your code and an endpoint.
2. **Create a Compute Module** and point it at the image.
3. **Configure resources** (CPU/memory/replicas) and the runtime mode.
4. **Deploy** the module so it runs on Foundry compute.
5. **Expose it** — call it from Functions, Actions, pipelines, or apps.
6. **Monitor** via observability (metrics, logs, traces).

## Example

You have a specialized geospatial routing library that won't run in a standard transform. Package it in a container, deploy it as an **interactive Compute Module**, and back a **Function** with it. A Workshop app then calls the Function to compute routes on demand, getting results in real time.

## How it connects to the rest of Foundry

- **Functions / Actions** — Compute modules can back callable logic.
- **Ontology / Workshop** — Apps invoke module-backed Functions.
- **Modeling** — An alternative path for serving custom models (see container models).
- **Observability** — Metrics, logs, and traces cover compute module execution.
- **Custom endpoints** — Deploy user-defined API endpoints alongside modules.

## Tips & gotchas for learners

- **Use it for the unusual** — custom runtimes/dependencies/always-on services, not routine pipelines.
- **Interactive modules cost continuously** since they stay running.
- **Mind security/networking** — containers run within governed boundaries.
- **Prefer Functions/transforms first** — only reach for containers when those don't fit.
- **Monitor health** — a down module breaks everything that calls it.

## Official documentation

- [Compute Modules: Overview](https://www.palantir.com/docs/foundry/compute-modules/overview)
- [Functions: Overview](https://www.palantir.com/docs/foundry/functions/overview)
- [Dev toolchain: Overview](https://www.palantir.com/docs/foundry/dev-toolchain/overview)
