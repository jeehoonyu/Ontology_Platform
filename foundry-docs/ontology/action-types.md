# Action Types (Actions)

> An action type is a predefined, reusable set of changes — edits to object properties, link creation/deletion, or side effects — that a user or application can trigger to modify the Foundry Ontology in a governed, consistent way.

## What it is

Action types live in the **Kinetic Layer** of the Foundry Ontology (alongside Functions), which is the part of the Ontology that enables change rather than just describing data. They solve the problem of letting many different users safely write back to operational data without each application needing its own ad-hoc editing logic. Instead of editing datasets directly, operators submit an action through a Workshop app, Object View, or API call; the action type applies the defined rules, validates submission criteria, commits the changes to the writeback dataset, and fires any configured side effects (notifications, webhooks, etc.). The result is a single, auditable, reusable definition of "how this kind of edit is allowed to happen."

## When to use it

- Operators need to update object properties through a form (e.g., change a ticket's status, assign a pilot to a flight).
- You need to create new objects or delete existing ones from a user-facing application.
- You want to link or unlink objects (e.g., associate an incident with an alert).
- You need conditional editing logic — only allow the edit when certain data conditions are met (submission criteria).
- You want to trigger downstream effects automatically after a change (send a notification, call a webhook, kick off a build).
- Complex multi-object updates are needed — use a function-backed action for cascading changes.

**When NOT to use it / alternatives:**
- For bulk, scheduled, pipeline-driven data transformation, use a Code Repository Transform, not an action.
- For purely read-only analysis or dashboards, actions are unnecessary.
- If the logic is too simple to warrant a form (e.g., a single-step pipeline job), a scheduled build or a direct dataset write may be more appropriate.

## Key concepts & terminology

- **Action type** — The reusable *definition* (template) of a set of Ontology edits; what users configure in Ontology Manager.
- **Action** — A single *execution* of an action type, i.e., one submission by a user or application.
- **Parameter** — An input variable on an action type; the form field a user fills in or that an application passes in programmatically.
- **Rule** — The logic inside an action type that translates parameter values into actual Ontology edits (modify property, create object, add/remove link) or other effects.
- **Submission criteria** — Conditions that must all be true for the action to be allowed to run; enforces business rules and data-quality gates at submit time.
- **Side effect** — An automated consequence fired after a successful submission: notifications, webhooks, or triggered builds.
- **Writeback dataset** — The dataset that captures the most up-to-date version of object data after user edits have been applied through actions.
- **Function-backed action** — An action type whose editing logic is defined by a custom TypeScript/Functions code rather than by simple declarative rules.
- **Ontology Manager** — The Foundry interface where action types (and the broader Ontology) are created and configured.

## Core capabilities / features

**Parameters**
- Parameters are the interface between the form/UI and the Rules engine.
- Each parameter has a type (object, string, integer, boolean, date, etc.) and configuration options: visibility (shown or hidden), editability (user-editable or read-only), default values, and multiple-choice constraints.
- Parameters can reference each other: a downstream parameter's dropdown can be filtered by the value already chosen in an upstream parameter.
- Parameters are available inside rules (to write values onto objects), inside submission criteria (to validate data), and inside side-effect templates (to personalise notifications).

**Rules**
- Rules define what actually changes in the Ontology when the action runs.
- Two categories: (1) *Ontology-edit rules* — modify a property value, create a new object, delete an object, add or remove a link between objects; (2) *effect rules* — trigger a side effect such as a notification.
- Rules reference parameter values by name, so the same rule re-runs with whatever inputs the user supplied.

**Submission Criteria**
- A set of conditions (comparisons) that must all pass before the action can be submitted.
- Condition types: *Current User Template* (check the submitting user's ID, group membership, or Multipass attributes) and *Parameter Template* (check a parameter value or the current value of an object property).
- Conditions combine with logical operators (all / any / none must be satisfied).
- Each failing criterion shows a custom error message to the user, explaining why the action is blocked.

**Side Effects**
- **Notifications** — Automatically alert Foundry users when the action runs. Recipients can be static (hardcoded users/groups), parameter-driven, object-property-driven, or function-computed. Subject and body are templated (up to 250 and 1,000 characters respectively, or up to 51,200 characters for custom HTML email). Maximum 500 recipients with template content; 50 with function-rendered content.
- **Webhooks** — Send an HTTP request to an external system after successful submission, enabling integration with third-party tools.
- **Schedule builds** — Trigger a downstream pipeline build to propagate changes into derived datasets.
- Side effects are not triggered if submission criteria fail.

**Function-Backed Actions**
- When declarative rules are not powerful enough (cascading updates across many linked objects, computed values derived from complex business logic), the action type can delegate its editing logic to a TypeScript Function.
- A function-backed action can read data from multiple objects, compute results, and write back to chains of related object types in a single transaction.
- Both action-type limits and function execution limits apply.

**Writeback**
- All edits committed by actions are written to the object type's writeback dataset, keeping the Ontology current without requiring a full pipeline re-run.
- The writeback dataset holds the authoritative "user-edited" view of the object data.

**Action Log**
- Every submission is recorded in an action log, providing an audit trail of who ran which action, when, and with what parameter values.

## How it works / typical workflow

1. **Open Ontology Manager** and select "New Action type."
2. **Set metadata** — provide a Display Name, API Name (unique identifier), description, and status.
3. **Add parameters** — define each input the user will supply (e.g., an object parameter to select the target ticket, a string parameter for the new status). Configure constraints such as multiple-choice allowed values.
4. **Write rules** — specify what the action does: e.g., "set the `status` property on the selected ticket to the value of the `newStatus` parameter." Add object-creation, deletion, or link rules as needed.
5. **Add submission criteria** — define conditions that must be met (e.g., the ticket's current status must be "Open" and the submitting user must belong to the "Support Team" group). Write a clear failure message for each criterion.
6. **Configure side effects** — optionally add a notification (choose recipients, write subject/body template), a webhook, or a scheduled build.
7. **Save and publish** the action type.
8. **Integrate into an application** — add an Actions widget in a Workshop module or Object View, referencing the action type's resource ID and mapping parameter defaults as needed.
9. **Test** — submit the action with valid and invalid data to confirm rules execute correctly and submission criteria block disallowed submissions.

## Example

**Scenario:** A support team uses Foundry to track service tickets. Each ticket is an Ontology object with `status`, `priority`, and `assignee` properties. You want to let support agents escalate a ticket (set priority to "P0" and reassign it) only when the ticket is currently "Open."

**Action type setup:**
- Parameter 1: `targetTicket` (Object — Demo Ticket type) — the ticket to escalate.
- Parameter 2: `newAssignee` (User) — who the ticket will be reassigned to.
- Rule 1: Set `priority` on `targetTicket` to `"P0"`.
- Rule 2: Set `assignee` on `targetTicket` to `newAssignee`.
- Submission criterion: `targetTicket.status` equals `"Open"` — failure message: "Ticket must be Open before it can be escalated."
- Side effect (notification): Notify `newAssignee` with subject "You have been assigned a P0 ticket" and a link to the ticket object.

A Workshop button labelled "Escalate Ticket" triggers this action; if the ticket is already closed, Foundry blocks submission and shows the error message.

For a more complex case — e.g., escalating the ticket and automatically closing all linked sub-tasks — you would use a **function-backed action** where the TypeScript function iterates over linked sub-task objects and sets each one's status to `"Closed"` in the same transaction.

```typescript
// Sketch of a function-backed action (TypeScript / Ontology Functions)
@Action
escalateTicketWithSubtasks(
  @ActionParam ticket: DemoTicket,
  @ActionParam newAssignee: string
): void {
  ticket.priority = "P0";
  ticket.assignee = newAssignee;
  for (const subtask of ticket.subTasks.all()) {
    subtask.status = "Closed";
  }
}
```

## How it connects to the rest of Foundry

- **Ontology** — Action types are a first-class citizen of the Ontology's Kinetic Layer; they directly read and write object properties and links defined in the Semantic Layer.
- **Workshop** — The most common consumer of action types; Workshop modules embed action forms as interactive widgets that operators fill in.
- **Object Views** — Object-level detail pages can expose action buttons directly on the object, with the target object pre-filled as a parameter default.
- **Functions** — Function-backed actions delegate editing logic to TypeScript Functions, enabling arbitrarily complex business rules.
- **Slate** — Older Foundry application builder that can also invoke action types via the Actions API.
- **Pipeline Builder / Code Repository** — Side effects can trigger scheduled builds, connecting action-driven edits to downstream data transforms.
- **Notifications / Compass** — The notification side effect integrates with Foundry's Workspace notification system.
- **Permissions / Multipass** — Submission criteria reference Multipass groups and user attributes, aligning data-editing governance with the organisation's identity system.

## Tips & gotchas for learners

- **Submission criteria vs. permissions** — Submission criteria are *data-conditional* checks (can this user edit *this specific object* given its current state?). They are separate from and run in addition to standard Foundry object-level permissions, which control whether the user can read or write the object type at all.
- **Writeback is not instant in pipelines** — The writeback dataset is updated immediately for Ontology reads, but downstream derived datasets that depend on the object type's source dataset will not reflect the change until the next pipeline build runs (unless you trigger a scheduled build as a side effect).
- **Notification data freshness** — Notification content uses the Ontology state *before* the action's edits are applied, so referencing the new property value in a notification body will show the old value.
- **Recipient limits** — Template-based notifications cap at 500 recipients; function-rendered notifications cap at 50. Plan accordingly for broadcast alerts.
- **Function-backed action limits** — These actions are subject to both standard action-type limits and function execution limits; they are not a backdoor to unlimited bulk writes.
- **API Name is immutable** — Once set, the API Name (used by Workshop, Slate, and code integrations) cannot be changed without breaking existing references. Choose it carefully.
- **Test with invalid data** — Always test that submission criteria *block* actions correctly, not just that valid submissions go through. This is the most common gap in testing.
- **Action log** — Use the action log for debugging and auditing; it records every submission including parameter values, making it easier to trace unexpected data changes.

## Official documentation

- [Action types — Overview](https://www.palantir.com/docs/foundry/action-types/overview)
- [Action types — Getting started](https://www.palantir.com/docs/foundry/action-types/getting-started)
- [Action types — Parameters overview](https://www.palantir.com/docs/foundry/action-types/parameter-overview)
- [Action types — Rules](https://www.palantir.com/docs/foundry/action-types/rules)
- [Action types — Submission criteria](https://www.palantir.com/docs/foundry/action-types/submission-criteria)
- [Action types — Side effects: Notifications](https://www.palantir.com/docs/foundry/action-types/notifications)
- [Action types — Side effects: Webhooks](https://www.palantir.com/docs/foundry/action-types/webhooks)
- [Action types — Function-backed actions overview](https://www.palantir.com/docs/foundry/action-types/function-actions-overview)
- [Action types — Permissions](https://www.palantir.com/docs/foundry/action-types/permissions)
- [Action types — Action log](https://www.palantir.com/docs/foundry/action-types/action-log)
- [Ontology — Overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Workshop — Use Actions in Workshop](https://www.palantir.com/docs/foundry/workshop/actions-use)
