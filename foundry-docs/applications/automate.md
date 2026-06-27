# Automate & Autopilot

> Automate lets you define condition-based automations that watch the Ontology and trigger effects — notifications, Actions, or schedules — when conditions are met; Autopilot extends this with workflow/task automation.

## What it is

Not every workflow should wait for a human to click a button. Automate is Foundry's rules engine for the Ontology: you define a **trigger/condition** (e.g., an object enters a state, a metric crosses a threshold, or on a schedule) and one or more **effects** (notify a user/group, run an Action, kick off a build). This turns the Ontology into a reactive system — alerts fire, records update, and processes advance automatically. **Autopilot** builds on this for task and workflow automation.

## When to use it

- You want alerts when objects change or thresholds are crossed.
- You need to auto-run Actions or builds in response to conditions/events.
- You're automating routine operational steps (assignment, escalation, notification).

**When NOT to use it / alternatives:** For user-driven steps, put **Actions/buttons** in Workshop. For data-pipeline scheduling, use **Schedules**. For complex AI decisioning, combine with **AIP Logic/agents**.

## Key concepts & terminology

- **Automation** — A configured rule: trigger/condition → effect(s).
- **Trigger** — What starts evaluation (object change, schedule, event/metric).
- **Condition** — The criteria that must hold for effects to run.
- **Effect** — The action taken: notification, Ontology Action, schedule/build, webhook.
- **Monitor** — Continuous watching of the condition.
- **Autopilot** — Workflow/task automation built on these primitives.

## Core capabilities / features

- **Condition-based triggers** — Fire on object state changes, thresholds, or schedules.
- **Multiple effect types** — Notifications, Ontology Actions, builds/schedules, webhooks.
- **Ontology-native** — Operates directly on object types and their properties.
- **Real-time + scheduled** — Works with streaming/near-real-time and periodic checks.
- **Notifications & escalation** — Alert users/groups when conditions occur.
- **Governed** — Respects permissions and audit logging.

## How it works / typical workflow

1. **Create an automation** targeting an object type/object set.
2. **Define the trigger/condition** (e.g., `status = OVERDUE`).
3. **Choose effect(s)** — notify the owner, run an "Escalate" Action, or start a build.
4. **Set evaluation cadence** (real-time vs scheduled).
5. **Enable** and **monitor** the automation.

## Example

Overdue-task escalation: an automation watches `Task` objects; when `dueDate < now AND status != DONE`, it runs an "Escalate" **Action** (sets priority high) and **notifies** the manager group. No one has to manually scan for overdue tasks.

## How it connects to the rest of Foundry

- **Ontology / Actions** — Automations trigger governed Action writeback.
- **Workshop** — Complements user-driven app workflows with automatic ones.
- **Streaming** — Real-time data can drive immediate automations.
- **Schedules** — Effects can launch builds; automations can be schedule-triggered.
- **AIP** — Combine with Logic/agents for AI-assisted automated decisions.

## Tips & gotchas for learners

- **Trigger + condition + effect** is the mental model for every automation.
- **Start with notifications** before wiring automations that mutate data.
- **Idempotency matters** — ensure repeated triggers don't double-apply effects.
- **Governance applies** — automated Actions still respect permissions and are audited.
- **Combine with AIP** for conditions/decisions that need reasoning.

## Official documentation

- [Automate: Overview](https://www.palantir.com/docs/foundry/automate/overview)
- [Action types: Overview](https://www.palantir.com/docs/foundry/action-types/overview)
- [Workshop: Overview](https://www.palantir.com/docs/foundry/workshop/overview)
