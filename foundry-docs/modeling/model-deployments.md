# Model Deployments (Live & Batch)

> A model deployment serves a released model for production inference — either as a live, real-time endpoint or as a scheduled batch job that scores data in bulk.

## What it is

Training a model is only half the job; a deployment is how the model actually produces value. Foundry supports two deployment modes. **Live deployments** serve the model behind a real-time endpoint for interactive, on-demand scoring (e.g., score a transaction as it happens). **Batch deployments** run the model on a schedule over a dataset/object set, writing predictions in bulk (e.g., nightly risk scores). Deployments are created from a released model in a Modeling Objective and integrate predictions back into the Ontology.

## When to use it

- **Live**: you need predictions on demand, in real time, inside apps or Functions.
- **Batch**: you need to score large volumes periodically and store results.

**When NOT to use it / alternatives:** During experimentation you don't deploy — you evaluate. Deploy only released, reviewed models.

## Key concepts & terminology

- **Deployment** — A served instance of a released model.
- **Live deployment** — A real-time inference endpoint.
- **Batch deployment** — Scheduled bulk inference over data.
- **Endpoint** — The callable interface of a live deployment.
- **Model-backed function** — A Function that calls a deployment for predictions.
- **Inference monitoring** — Tracking latency, throughput, and errors.

## Core capabilities / features

- **Live (real-time) serving** — Low-latency, on-demand predictions.
- **Batch (scheduled) serving** — Bulk scoring written back to datasets/objects.
- **Ontology integration** — Predictions become object properties or Function outputs.
- **Scalability** — Configure resources/replicas for live endpoints.
- **Monitoring** — Observe inference metrics, errors, and drift signals.
- **Governed** — Deployments respect permissions and audit logging.

## How it works / typical workflow

1. **Release a model** in a Modeling Objective.
2. **Create a deployment** — choose **live** or **batch**.
3. For **live**, configure the endpoint and resources; for **batch**, set the input data and **schedule**.
4. **Wire predictions** into the Ontology (object properties) or call via a **model-backed Function**.
5. **Monitor** inference performance and retrain/redeploy as needed.

## Example

- **Live:** A fraud model is deployed as a real-time endpoint; a Function calls it during transaction processing so a Workshop app shows risk instantly.
- **Batch:** A churn model is deployed as a nightly batch job that writes `churnRisk` onto every `Customer` object for the retention team's dashboard.

## How it connects to the rest of Foundry

- **Modeling Objectives** — Deployments serve released models from objectives.
- **Functions / Ontology** — Model-backed Functions and object properties consume predictions.
- **Workshop** — Apps surface real-time and batch predictions.
- **Schedules** — Batch deployments run on schedules.
- **Observability** — Inference is monitored via traces/metrics.

## Tips & gotchas for learners

- **Live vs batch is a latency decision** — real-time need vs periodic bulk scoring.
- **Live endpoints cost continuously**; batch only runs on schedule.
- **Monitor for drift** — model quality degrades as data shifts; plan retraining.
- **Deploy released models only** — never serve un-reviewed experiments.
- **Integrate with the Ontology** so predictions are usable by apps and automations.

## Official documentation

- [Model integration: Deployments](https://www.palantir.com/docs/foundry/model-integration/deployments)
- [Modeling Objectives: Overview](https://www.palantir.com/docs/foundry/modeling-objectives/overview)
