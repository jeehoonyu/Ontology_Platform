# Markings & Classification-Based Access

> Markings are mandatory access controls applied to data that require special protection; combined with restricted views and granular policies, they enforce row- and column-level security that even resource editors cannot bypass.

## What it is

Project roles decide who can open a resource, but some data needs stronger, non-discretionary control. **Markings** are mandatory controls: to see marked data, a user must be explicitly granted that marking — and no project-level role can override it. This enables **classification-based access** (think clearance levels) and, via **restricted views**, fine-grained **row- and column-level** security so different users see different subsets of the same dataset.

## When to use it

- Data has regulatory, privacy, or security classifications (PII, restricted, secret).
- Different users must see different rows/columns of the same dataset.
- You need controls that can't be undone by a project editor.

**When NOT to use it / alternatives:** For ordinary team access use **roles/permissions**; to encrypt/tokenize values use **Cipher**.

## Key concepts & terminology

- **Marking** — A mandatory control attached to data; users need explicit grant to access.
- **Mandatory control** — A restriction that overrides discretionary (role-based) access.
- **Classification** — A level/category (e.g., clearance) driving access.
- **Restricted view** — A derived view exposing only the rows/columns a user is allowed to see.
- **Row-level security** — Filtering rows per user/attribute.
- **Column-level security** — Hiding/masking columns per user/attribute.
- **Policy** — The rule mapping user attributes to allowed data.

## Core capabilities / features

- **Mandatory markings** — Non-discretionary controls that cascade with the data.
- **Classification-based access** — Grant data based on clearance/category.
- **Restricted views** — Per-user row/column visibility over a shared dataset.
- **Granular policies** — Attribute-driven rules for fine-grained control.
- **Propagation** — Markings follow data through transforms/derived datasets.
- **Ontology coverage** — Controls extend to object types and properties.

## How it works / typical workflow

1. **Define markings/classifications** for sensitive data categories.
2. **Apply markings** to datasets/resources (they propagate downstream).
3. **Grant markings** to the users/groups cleared for them.
4. For partial visibility, **create restricted views** with row/column policies.
5. Users automatically see only data their grants/policies permit.
6. **Audit** access to marked data.

## Example

A `patients` dataset is marked **PHI**. Only the `clinical-staff` group is granted the PHI marking, so even a project editor without it can't read the data. A **restricted view** further limits nurses to rows for their own ward and masks the SSN column, while physicians see more — all from the same underlying dataset.

## How it connects to the rest of Foundry

- **Projects & permissions** — Markings layer mandatory controls on top of roles.
- **Datasets / transforms** — Markings propagate through derived data.
- **Ontology** — Object/property access respects markings and policies.
- **Cipher** — Complementary value-level encryption for the most sensitive fields.
- **Audit logs** — Marked-data access is logged for compliance.

## Tips & gotchas for learners

- **Markings override roles** — that's the whole point; editors can't bypass them.
- **Markings propagate** — derived datasets inherit the source's markings.
- **Restricted views = row/column security** — use them for partial visibility.
- **Grant markings deliberately** — over-granting defeats the control.
- **Combine with Cipher** when even authorized viewers shouldn't see raw values.

## Official documentation

- [Security: Markings](https://www.palantir.com/docs/foundry/security/markings)
- [Security: Overview](https://www.palantir.com/docs/foundry/security/overview)
