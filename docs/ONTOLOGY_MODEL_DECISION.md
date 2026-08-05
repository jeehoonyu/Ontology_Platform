# Ontology Model: Validation and Upgrade Decision

Stated 2026-08-03, after reading the implementation and researching the alternatives.

## What the model already is

The legacy `ObjectType`/`LinkType` in `oms/app/models.py` is a thin property bag and is
misleading if read alone. The real model is the normalized layer in
`oms/app/ontology_core.py`, and it is substantially richer than a property graph:

- A **21-type base vocabulary** with declared categories: numeric (`byte` through
  `decimal`), text, temporal (`date`, `timestamp`), **spatial (`geopoint`, `geoshape`)**,
  collection (`array`, `struct`), reference (`attachment`, `mediaReference`,
  `timeSeries`), security (`marking`, `cipherText`), and ML (`vector`).
- **Shared property types**, so a property's metadata is defined once and reused across
  object types.
- Per-property `status`, `required`, `unit`, `geometry_type`, `render_hint`, min/max,
  enum, regex, indexed and sensitive flags.
- Object-type profiles carrying `api_name`, `primary_key`, `title_key`, `icon`, `color`,
  and property groups, with PascalCase/camelCase API-name validation.
- Immutable revisions, breaking-change classification, and generated typed SDKs.

This is a sound foundation. The problem is not the model's expressiveness.

## The two real gaps

### 1. Interfaces exist and are not surfaced

**Correction.** An earlier revision of this document said interfaces were a stub, on the
strength of `ontology_core.py` reporting
`"interfaces": {"summary": {"configured": False}, "rows": []}`. That reading was wrong.
The string is a hardcoded placeholder in one UI-state section handler, sitting beside
identical placeholders for `object_views` and `automations`. It reports `False`
unconditionally and never consults interface data at all.

Interfaces are substantially implemented:

- `oms/app/ontology_interfaces.py` defines `OntologyInterface` with properties and
  `extends`, plus shared property types with apply and detach.
- `oms/app/ontology_interfaces_ops.py` resolves inheritance by breadth-first traversal of
  the `extends` chain, cycle-safe, with nearer declarations overriding inherited ones, and
  resolves inherited link constraints as well.
- Routes exist for interface CRUD, implementers, and object-type conformance checking, and
  both routers are registered in `main.py`.
- `oms/test_ontology_interfaces_inheritance.py` and `test_ontology_interfaces_ops.py`
  cover them.

So the ontology does have polymorphism. What it does not have is polymorphism the product
uses. The Ontology Manager shows every object type as having no interfaces because that
endpoint returns a constant. Nothing in the query layer accepts an interface where it
accepts an object type, and the generated SDKs do not emit interface types.

The correction matters for planning: the work is not building the construct, it is
consuming it. That is a smaller and differently shaped job than a from-scratch model
change, and it is the reason the staged plan below now starts at consumption.

### 2. The UI discards the semantics the ontology records

Measured by `oms/audit_extensibility.py` on 2026-08-03:

```
declared property base types      21
semantic types the UI can render  0 of 13
interfaces configured             False
concrete object-type couplings    1
```

`render_hint` is written by the ontology editor and **read by nothing**. Object Explorer
renders every property through a generic `formatValue`, so a `geoshape` arrives as raw
GeoJSON text, a `timeSeries` as a reference string, a `marking` as its identifier, and a
`decimal` loses its unit.

Note what the low coupling number does *not* mean. The UI is not admirably generic; it is
type-blind. It never branches on object type because it never consults type at all. Those
are opposite conditions that produce the same count, and only the renderable-types
reading distinguishes them.

## Decision: extend the current model, do not adopt RDF/OWL

The tempting "more advanced model" is RDF/OWL with a reasoner. **Recommendation: do not.**

- OWL's open-world assumption means absence of a fact is unknown rather than false. This
  platform's guarantees are the opposite: governed actions, append-only evidence, and
  deterministic risk scoring all depend on closed-world evaluation. Reasoners also make
  inferred facts hard to attribute, which conflicts with an append-only record carrying
  actor, source, and evidence for every change.
- The typed property graph already maps cleanly onto PostgreSQL JSONB with expression
  indexes, which is what carries the 10M-object / 50M-link measurements. A triple store
  would forfeit that and the DuckDB snapshot path with it.
- The gap is not paradigm-level. It is one missing construct — polymorphism — that is
  strictly additive to what exists.

RDF/OWL would be the right answer if the requirement were federating with external
published vocabularies or performing inference over incomplete data. Neither is in scope.

**The upgrade is: add interfaces to the existing typed property graph, and make the
rendering layer consume the semantics already recorded.**

## Staged plan

Each stage is independently valuable and independently verifiable.

**Stage 1 — Interfaces in the ontology. Largely done.** Interface types, `extends`
inheritance with cycle-safe resolution, shared property types, and conformance checking
already exist. What remains is narrower than it first appeared: conformance is checked by
property *name* against the legacy `ObjectType.properties` bag rather than by base type
against the normalized profile, so a `location` string would satisfy an interface asking
for a `geopoint`; implementers are inferred by scanning every object type rather than
declared and indexed; and `OntologyInterface` carries no `project_id`, unlike every other
ontology resource. Close those three before building on top.

**Stage 2 — Interface-scoped queries.** `/api/v1` object and graph queries accept an
interface where they accept an object type, returning instances across every implementer
with a discriminator. This is the load-bearing stage for heavy data: it needs an index
strategy spanning types, not a per-type scan stitched in the application. Note that even
Foundry ships this partially — search and sort by interface are supported while
aggregation is still in development — so aggregate pushdown should be treated as its own
milestone rather than assumed.

**Stage 3 — Semantic rendering.** A registry mapping base type and `render_hint` to a
renderer, consumed by every data surface. `geopoint`/`geoshape` render as geometry,
`timestamp` in the viewer's zone, `decimal` with its unit, `marking` as a classification
chip, `attachment`/`mediaReference` as links, `vector` suppressed by default. Raises
`renderable_base_types` from 0.

**Stage 4 — Interface-driven views.** Views declare the interface they serve rather than
the types they list. A new implementing type appears in them with no UI change. This is
the stage that makes the ratchet meaningful.

**Stage 5 — Interfaces in generated SDKs.** Emit interface types so external programs
built on OntologyOS code against capability contracts. This is what makes "data shown in
different programs we build" a property of the model rather than a per-program effort.

## What this buys GIS

GIS is not a later addition in the sense of being absent: `geopoint` and `geoshape` are in
the base vocabulary, and MGRS, geofences, radius search, map layers, and a Leaflet
workspace already exist. What is missing is that the map must be told which object types
are mappable.

With Stage 1 and Stage 4, a `Geolocatable` interface — declaring a `geopoint` or
`geoshape` property — makes any implementing type appear on the map automatically. Doing
interfaces before the next GIS expansion is what prevents that expansion from hard-coding
another type list that has to be maintained by hand.

## Heavy and complex data

Two distinct problems, worth separating:

- **Heavy** is measured and largely answered: 10M objects, 50M links, bounded p95s, JSONB
  expression indexes, keyset pagination, DuckDB snapshots over 10M-row partitions.
- **Complex** is not. `struct` and `array` are declared base types, but nested-structure
  querying at scale has no benchmark, and interface-scoped queries across many types have
  no index strategy yet. Stage 2 should carry its own gate rather than inheriting the
  existing scale evidence, per the non-completion rule.
