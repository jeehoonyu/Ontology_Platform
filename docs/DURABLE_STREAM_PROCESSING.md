# Durable Event-Time Stream Processing

OntologyOS processes project-owned stream records through durable, deterministic event-time processors. The runtime is local by default, PostgreSQL-safe in production, and keeps state, output, and evidence in one transaction.

## Durable Event Routing

Published platform events can enter the same processing runtime through project-owned event-stream bindings. Create a binding with `POST /api/v1/event-stream-bindings`; filters support glob patterns for topics, event types, and aggregate types, plus explicit ontology object-type IDs. The binding targets one project stream and retains a durable event-log cursor.

Route synchronously with `POST /api/v1/event-stream-bindings/{id}/route`, or enqueue the `event.stream.route` job through `/enqueue`. Each matched event is written as a complete immutable event envelope. A unique `(binding_id, event_id)` receipt and deterministic stream-record ID prevent duplicate delivery on retry. PostgreSQL locks the binding while scanning and allocating stream sequences, so concurrent routers serialize without skipping or duplicating events. The cursor advances across unmatched events as well as matched events, avoiding repeated filter scans.

Binding state and exact receipts are included in project snapshots. A failed routing transaction rolls back its stream records, receipts, stream sequence allocation, and cursor together; a worker retry resumes from the prior committed cursor.

## Processing Contract

Create a processor with `POST /api/v1/streams/processors`. A processor binds one stream to:

- an optional event timestamp field;
- an optional partition key;
- a partition-local watermark and allowed-lateness interval;
- `quarantine`, `drop`, or `accept` late-data policy;
- an optional tumbling window and `count`, `sum`, `avg`, `min`, or `max` aggregation;
- an optional output dataset;
- batch, backlog, and `reject` or `warn` backpressure limits.

Every stream record receives an atomic stream-scoped arrival sequence. Event time controls watermarks and windows; arrival sequence controls deterministic consumption. PostgreSQL allocates sequences atomically across publishers and fences concurrent processors with a row lock.

A processor can optionally bind a second project stream with `join_stream_id`, left/right key fields, and an event-time tolerance. Inputs from either side are normalized into indexed join state. Either side may arrive first; a later opposite-side record evaluates the bounded interval and emits every matching pair. Unique pair receipts and stable output IDs make many-to-many correlation replay-safe. Source-prefixed partition watermarks preserve independent lateness decisions for both streams, and pair receipts plus materialized output commit with the input receipts and run evidence.

Run immediately with `POST /api/v1/streams/processors/{id}/process`, or enqueue a durable job with `/enqueue` and execute it through the `stream.process` worker capability. Jobs retain leases, retries, cancellation, idempotency, audit evidence, Ops events, and runtime observations.

## Correctness and Recovery

- A unique `(processor_id, record_id)` receipt makes record handling exactly once within a processor.
- Partition watermarks prevent one fast source from making another partition late.
- Invalid and late records retain payload, reason, watermark, and review status in quarantine.
- Window output uses stable IDs, so retries cannot duplicate emitted windows.
- Processor state, receipts, window output, run evidence, and the durable job commit together.
- Injected or real failures roll back the complete batch and leave input records available for retry.
- Producer-side backlog admission prevents unbounded local queues.
- Project snapshots preserve processor definitions, partition/window state, receipts, quarantine, and run history.
- Project snapshots also preserve normalized two-stream join inputs and exact pair receipts.

Use `GET /api/v1/streams/processing/summary` for backlog and pressure status, processor detail for partition/window state, and `/quarantine` for late-data review evidence. Project readiness reports failed runs, capacity breaches, and pending quarantine.

## Verification

```powershell
python oms/test_durable_stream_processing.py
python oms/test_durable_stream_processing_migration.py
python oms/test_event_to_stream_routing.py
python oms/test_event_stream_bindings_migration.py
python oms/test_cross_stream_interval_join.py
python oms/test_cross_stream_join_migration.py
python oms/test_cross_stream_join_tenancy.py
```

With a migrated PostgreSQL database:

```powershell
python oms/verify_stream_processing_postgres.py
python oms/verify_event_stream_routing_postgres.py
python oms/verify_cross_stream_join_postgres.py
```

The PostgreSQL rehearsal publishes 100 records from ten concurrent publishers, proves contiguous unique arrival sequences, then proves two concurrent processor calls produce one receipt per record without duplicate work.

The event-routing rehearsal concurrently routes 100 durable platform events through one binding and proves exactly 100 contiguous stream records, unique event receipts, and zero duplicate work.

The interval-join rehearsal lets two PostgreSQL workers race over 50 left and 50 right records. One serialized run consumes all 100 inputs and emits exactly 50 unique correlated outputs; the competing run observes no backlog and cannot duplicate pair receipts.

This increment does not claim a distributed stream-compute engine. Multi-node partition assignment, broker-driven consumer groups, outer joins, state-retention compaction, and sustained production throughput benchmarks remain release work.
