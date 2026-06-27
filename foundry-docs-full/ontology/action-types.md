<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ONTOLOGY</b><br>
<span style="font-size:22px"><b>Action Types</b></span><br>
<span style="color:#ABB3BF">Structured, reusable definitions of changes that users can make to Ontology objects, properties, and links — enforced through validation rules and committed as atomic transactions.</span>
</td></tr></table>

## What it is

An **Action Type** is the definition of a set of changes or edits to objects, property values, and links that a user can take at once. It is the "kinetic" layer of the Ontology: where object types and link types describe *what* the data model looks like, action types describe *how* authorized users can change it. A single action type encapsulates input parameters, transformation rules, submission criteria, and optional side effects — and because the definition lives centrally in the Ontology, every Foundry application that exposes the action automatically uses the same logic and validations.

---

## How it works

Action types are configured in the **Ontology Manager** and executed wherever they are surfaced. The following is the end-to-end mechanical model.

### 1. Definition (Ontology Manager)

An action type is created as a named resource in the Ontology. During creation you choose the **operation category**:

- **Change object(s) → Modify** — update property values on existing objects
- **Change object(s) → Create** — instantiate a new object with specified properties
- **Change object(s) → Delete** — remove existing objects
- **Manage links** — create or remove many-to-many link type connections

The target **object type** (or interface) is selected, binding the action to that schema.

### 2. Parameters

Parameters are the typed inputs collected from the user at runtime. They are auto-generated from rules but can be refined on the **Forms** tab:

- **Constraint mode**: `User input` (free field) or `Multiple choice` (allowlist of values)
- **Default values**: a static value, the current user's identity, the current timestamp, or a property of an object parameter
- **Visibility**: each parameter can be marked hidden or disabled based on validity conditions, so forms are pre-populated where possible

### 3. Rules (the transformation logic)

Rules are the core of an action type. There are three categories:

**Ontology rules** — directly read and write Ontology data:

| Rule | Effect |
|---|---|
| `Create object` | Instantiates a new object; requires a primary key |
| `Modify object(s)` | Updates properties on objects supplied via parameters |
| `Create or modify object(s)` | Upsert semantics — creates if absent, updates if present |
| `Delete object(s)` | Removes objects by primary key |
| `Create link(s)` | Establishes many-to-many connections |
| `Delete link` | Removes many-to-many connections |
| `Function rule` | Delegates all edit logic to a TypeScript Ontology edit function; no other rules may coexist with this |
| Interface-based rules | Same CRUD operations scoped to any object type that implements a given interface |

Property mapping sources inside each rule include: matched parameters, properties of an object parameter, static values, current user ID, or the current UTC timestamp.

**Side effect rules** — triggered after (or optionally before) edits commit:

- **Notification rule** — dispatches a Foundry notification to specified users; message content reflects the *pre-edit* Ontology state
- **Webhook rule** — sends an HTTP request to an external system; can be configured to fire before or after edits apply
- **Schedule rule** — triggers a build with parameters passed into parameterized transforms

### 4. Submission Criteria

Submission criteria are conditions evaluated *before* the transaction is allowed to commit. Configured on the **Security & Submission Criteria** tab, they accept parameter-based or property-based comparisons (e.g., "Ticket Status must be Open"). If a criterion fails, a custom error message is shown to the user and the transaction is blocked.

### 5. Function-Backed Actions

When business logic exceeds what declarative rules can express, action types can call a **TypeScript Ontology edit function** (a "Function rule"). This unlocks:

- Conditional transformations computed from data across multiple object types
- Simultaneous modification of interconnected objects (e.g., one Incident and all its linked Alerts)
- Auto-creation of object networks with relationships in a single submit

Function-backed actions are still subject to action type and function execution limits. The backing function must have **Edits** provenance enabled to participate in action logging.

### 6. Execution and commit

When a user submits an action:

1. Submission criteria are evaluated; the transaction is blocked if any fail.
2. Side effect rules configured to fire *before* edits execute.
3. All ontology rules (or the function rule) execute as **a single atomic transaction** — all changes commit together or none do.
4. Side effect rules configured to fire *after* edits execute (notifications, webhooks).
5. If action logging is enabled, an **action log object** is created in the Ontology, linked to every affected object.

---

## User interface

Action types are authored in <span style="color:#8ABBFF">**Ontology Manager**</span> and consumed in <span style="color:#8ABBFF">**Object Views**</span>, <span style="color:#8ABBFF">**Object Explorer**</span>, and <span style="color:#8ABBFF">**Workshop**</span>.

### Authoring in Ontology Manager

The creation wizard asks for a display name and operation category. Once created, the action type opens to a tabbed editor:

<table style="border-collapse:collapse;width:100%">
<tr style="background:#1C2127;color:#ABB3BF">
  <th style="padding:8px 12px;border:1px solid #383E47;text-align:left">Tab</th>
  <th style="padding:8px 12px;border:1px solid #383E47;text-align:left">Contents</th>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Rules</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Add/remove ontology rules and side effect rules; configure property mapping sources</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Forms</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Refine auto-generated parameters — constraint mode, default values, labels, order</td>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Security & Submission Criteria</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Define who can execute the action and what conditions gate submission</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Notifications</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Configure notification and webhook side-effect rules</td>
</tr>
</table>

### Action state chips

<span style="color:#238551"><b>● active</b></span> — action type is published and executable  
<span style="color:#C87619"><b>● draft / stale</b></span> — saved but not yet published or behind a schema change  
<span style="color:#CD4246"><b>● blocked</b></span> — submission criteria not met; error shown to user  
<span style="color:#2D72D2"><b>● primary action button</b></span> — the call-to-action rendered in Object Views and Workshop  

### Runtime surfaces

- **Object Views** — an <span style="color:#8ABBFF">Actions widget</span> is added to the view; each button is bound to an action type RID and can be configured to open a form or apply immediately with preset defaults.
- **Object Explorer** — an <span style="color:#8ABBFF">Actions dropdown</span> appears in the Exploration View (bulk) and an <span style="color:#8ABBFF">Object Actions dropdown</span> appears in the Object View (single or bulk); a third location appears in the Linked Objects section.
- **Workshop** — a <span style="color:#8ABBFF">Button group widget</span> binds to action types with icon, label, tag-style, and layout customization. Multiple button variants of the same action type can coexist with different default values (e.g., "Delay 10 min" vs "Delay 30 min").

When triggered, a **parameter form** renders with pre-populated, hidden, or disabled fields as configured. On submit the transaction fires and — if successful — the UI reflects updated object state immediately.

---

## Worked example

**Scenario**: A support team wants to let agents reprioritize open tickets from an Object View without directly editing raw data.

1. In **Ontology Manager**, create an action type named *Change Ticket Priority*, operation: **Modify**.
2. Select the `Demo Ticket` object type; add the `Priority` property to the rule.
3. On the **Forms** tab, set the `Priority` parameter constraint to **Multiple choice** with values `P0`, `P1`, `P2`.
4. On the **Security & Submission Criteria** tab, add a condition: `Ticket Status` equals `Open`; set failure message: *"Only open tickets can be reprioritized."*
5. In the **Ticket Object View**, add an **Actions widget** and paste the action type's RID. Set the `Ticket` parameter default to `Current object` and mark it **Hidden** so the form only shows the `Priority` field.
6. Publish the Object View.

An agent opens a ticket, clicks **Change Ticket Priority**, selects `P0`, and submits. Foundry creates a single atomic transaction updating the `priority` property, blocks the submit if the ticket is closed, and records an action log entry with the agent's user ID, timestamp, and the new priority value.

---

## Documentation map

- **Overview** — what action types are and their role in the Ontology
- **Getting started** — step-by-step tutorial: create, configure, add to Object View, publish
- **Rules** — full reference for all 12 ontology rules and side effect rules
- **Parameters** — configuring inputs: constraints, defaults, visibility, performance
- **Submission criteria** — gating conditions and failure messaging
- **Function-backed actions → Overview** — delegating logic to TypeScript Ontology edit functions
- **Function-backed actions → Tutorial** — hands-on walkthrough
- **Inline edits** — quick edits surfaced directly in table/grid widgets
- **Actions on structs** — applying action logic to struct-typed properties
- **Actions on interfaces** — interface-scoped create/modify/delete rules
- **Notifications** — configuring notification side-effect rules
- **Webhooks** — configuring external HTTP side-effect rules
- **Use actions in the platform** — how actions surface in Object Explorer, Object Views, Workshop
- **Action log** — recording submissions as Ontology object types for audit and analysis
- **Permissions & access control** — role-based execution gating
- **Monitoring** — observability for action execution
- **Undo / revert** — reversing committed action transactions
- **Scaling limits** — execution and function limits
- **Marketplace integration** — pre-built action types in Foundry Marketplace products

---

## Official documentation

- [Action types · Overview](https://www.palantir.com/docs/foundry/action-types/overview)
- [Action types · Getting started](https://www.palantir.com/docs/foundry/action-types/getting-started)
- [Action types · Rules](https://www.palantir.com/docs/foundry/action-types/rules)
- [Action types · Function-backed actions · Overview](https://www.palantir.com/docs/foundry/action-types/function-actions-overview)
- [Action types · Use actions in the platform](https://www.palantir.com/docs/foundry/action-types/use-actions)
- [Action types · Action log](https://www.palantir.com/docs/foundry/action-types/action-log)
- [Action types · Inline edits](https://www.palantir.com/docs/foundry/action-types/inline-edits)
- [Action types · Actions on structs](https://www.palantir.com/docs/foundry/action-types/actions-on-structs)
- [Ontology · Overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Ontology · Core concepts](https://www.palantir.com/docs/foundry/ontology/core-concepts)
