# Audit Logs & Data Governance

> Foundry's governance layer includes robust audit logging, a sensitive data scanner, data-lifetime/retention controls, and checkpoint/approval workflows for sensitive actions.

## What it is

Beyond who-can-access (permissions, markings) and what's-readable (Cipher), enterprises must answer "what happened, what's sensitive, how long do we keep it, and who approved this?" Foundry provides **audit logs** that record access and actions for investigation; a **sensitive data scanner** that flags protected data patterns; **data-lifetime** policies for retention/deletion; and **checkpoints/approvals** that require review before sensitive actions proceed.

## When to use it

- You must prove who accessed or changed what (compliance, investigations).
- You need to discover where sensitive data (PII, secrets) lives.
- You must enforce retention/deletion policies.
- Certain actions should require explicit human approval.

**When NOT to use it / alternatives:** For access grants use **roles/markings**; for value protection use **Cipher**. Governance complements, not replaces, those.

## Key concepts & terminology

- **Audit log** — A tamper-evident record of access and actions across the platform.
- **Sensitive Data Scanner** — Tooling that detects protected data patterns.
- **Data lifetime / retention** — Policies controlling how long data is kept and when it's deleted.
- **Checkpoint** — A required review gate before a sensitive action proceeds.
- **Approval** — A request-and-authorize workflow for gated actions.
- **Governance policy** — Rules tying these controls together.

## Core capabilities / features

- **Security audit logging** — Detailed records for detecting and investigating potential abuse.
- **Sensitive data scanning** — Identify and flag protected information across datasets.
- **Data lifetime management** — Enforce retention and deletion policies.
- **Checkpoints & approvals** — Require review/authorization for sensitive operations.
- **Investigation support** — Search and analyze audit events.
- **Compliance alignment** — Evidence for regulatory and internal audits.

## How it works / typical workflow

1. **Enable audit logging** (typically platform-managed) and learn to query it.
2. **Run the sensitive data scanner** to map where protected data lives.
3. **Apply markings/Cipher** to what the scanner finds.
4. **Define data-lifetime policies** for retention/deletion.
5. **Configure checkpoints/approvals** on sensitive actions.
6. **Investigate** via audit logs when reviewing incidents or compliance.

## Example

A privacy team runs the **sensitive data scanner**, which flags an un-marked column containing emails. They apply a **PII marking** and a **data-lifetime** policy to delete it after 12 months. A new export action is gated behind a **checkpoint** requiring manager approval, and every export is recorded in the **audit log** for the annual compliance review.

## How it connects to the rest of Foundry

- **Markings & Cipher** — Governance findings drive what gets marked/encrypted.
- **Projects & permissions** — Access events are audited; approvals gate sensitive grants/actions.
- **Ontology / Actions** — Sensitive Actions can require checkpoints/approvals.
- **Marketplace/DevOps** — Governance applies to packaged/promoted products.

## Tips & gotchas for learners

- **Audit logs are for accountability** — know how to search them before you need to.
- **Scan, then protect** — discovery (scanner) feeds controls (markings/Cipher/retention).
- **Retention is a control too** — keeping data forever is a liability.
- **Checkpoints add friction by design** — apply them to genuinely sensitive actions.
- **Governance is layered** — audit + scanning + retention + approvals work together.

## Official documentation

- [Security: Audit logs](https://www.palantir.com/docs/foundry/security/audit-logs)
- [Security: Overview](https://www.palantir.com/docs/foundry/security/overview)
