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

A processor can optionally bind a second project stream with `join_stream_id`, left/right key fields, an event-time tolerance, and `inner`, `left`, `right`, or `full` join semantics. Inputs from either side are normalized into indexed join state. Either side may arrive first; a later opposite-side record evaluates the bounded interval and emits every matching pair. Unique pair receipts and stable output IDs make many-to-many correlation replay-safe. Source-prefixed partition watermarks preserve independent lateness decisions for both streams, and pair receipts plus materialized output commit with the input receipts and run evidence.

Outer joins finalize an unmatched input only when the opposite side's watermark is strictly greater than the input event time plus the join tolerance. The strict boundary preserves an event exactly at the watermark as admissible. `POST /api/v1/streams/processors/{id}/watermarks` advances a side/key watermark monotonically, including idle keys that cannot advance from data. A regression returns `WATERMARK_REGRESSION`. Each unmatched output has a stable ID and immutable `stream_join_outer_receipts` record, so repeated watermark calls, worker retries, compaction, and snapshot restore cannot duplicate it. Outer joins reject the unbounded `accept` late-data policy because finalized unmatched output would otherwise be retractable.

Join state is bounded for `quarantine` and `drop` late-data policies. After each batch, the processor inspects only join keys touched by that batch and removes inputs older than both source watermarks minus the join tolerance and a conservative one-day retention interval. Compaction uses bounded indexed deletes, commits with the processing run, and records its cutoff and count in run metrics. Use `POST /api/v1/streams/processors/{id}/compact` for a dry run or bounded maintenance pass with an explicit `retention_seconds` and `max_inputs`. Exact pair receipts and materialized outputs remain append-only evidence. Processors configured to accept arbitrary late data report `SKIPPED` because that policy requires unbounded match state.

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
- Project snapshots preserve outer-finalization receipts, opposite watermarks, join semantics, and run metrics.
- Watermark-safe compaction bounds retained join inputs without deleting exact-pair or output evidence.

Use `GET /api/v1/streams/processing/summary` for backlog and pressure status, processor detail for partition/window state, and `/quarantine` for late-data review evidence. Project readiness reports failed runs, capacity breaches, and pending quarantine.

## Verification

```powershell
python oms/test_durable_stream_processing.py
python oms/test_durable_stream_processing_migration.py
python oms/test_event_to_stream_routing.py
python oms/test_event_stream_bindings_migration.py
python oms/test_cross_stream_interval_join.py
python oms/test_cross_stream_outer_join.py
python oms/test_stream_join_compaction.py
python oms/test_cross_stream_join_migration.py
python oms/test_stream_outer_join_migration.py
python oms/test_cross_stream_join_tenancy.py
```

With a migrated PostgreSQL database:

```powershell
python oms/verify_stream_processing_postgres.py
python oms/verify_event_stream_routing_postgres.py
python oms/verify_cross_stream_join_postgres.py
python oms/verify_cross_stream_outer_postgres.py
```

The PostgreSQL rehearsal publishes 100 records from ten concurrent publishers, proves contiguous unique arrival sequences, then proves two concurrent processor calls produce one receipt per record without duplicate work.

The event-routing rehearsal concurrently routes 100 durable platform events through one binding and proves exactly 100 contiguous stream records, unique event receipts, and zero duplicate work.

The interval-join rehearsal lets two PostgreSQL workers race over 50 left and 50 right records. One serialized run consumes all 100 inputs and emits exactly 50 unique correlated outputs; the competing run observes no backlog and cannot duplicate pair receipts. It then advances both source watermarks and races two compaction calls, proving one locked call removes each expired input while the other observes no duplicate work and all exact-pair/output evidence remains.

The outer-join rehearsal races two explicit watermark advances over 50 retained left inputs. PostgreSQL serializes the processor: one call emits 50 immutable unmatched receipts and outputs, while the other emits zero. Later matching records are quarantined behind the finalized watermark and cannot retract or duplicate output. The SQLite contract also bounds finalization to one output while an older matched row shares the same join key, proving matched candidates are excluded before the SQL limit and cannot starve eligible unmatched rows.

The outer-finalization partition rehearsal holds receipt inserts inside an open PostgreSQL transaction, observes that exact INSERT in `pg_stat_activity`, and terminates its backend. The failed transaction leaves zero watermark, receipt, or dataset output state. Recovery emits all 60 retained rows exactly once; concurrent replay emits zero, and late counterparts are quarantined without retracting the finalized output.

This increment does not claim a distributed stream-compute engine. Multi-node partition assignment, broker-driven consumer groups, and sustained production throughput benchmarks remain release work.
