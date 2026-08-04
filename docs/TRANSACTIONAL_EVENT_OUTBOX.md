# Transactional Event Outbox

OntologyOS records delivery intent in `event_outbox` in the same database transaction as every new audit event, operational event, or append-only ontology object change. A SQLAlchemy session invariant covers shared and legacy audit/Ops writes. The ontology runtime uses the same idempotent enqueue primitive directly so object creation, update, retirement, and reactivation become stream inputs without calling a network broker during commit.

Object changes publish on `ontologyos.object_change`. Their envelope includes the temporal evidence ID, object type and identity, object version, before/after state, changed fields, source, ontology revision, valid/transaction time, evidence, and materialization lifecycle. The outbox idempotency key is derived from the immutable object-change event ID. Batch hydration uses an O(1) transaction-local pending map and does not query for a key whose newly generated evidence ID is already unique.

The production worker capability `event.dispatch` claims eligible rows with a lease. PostgreSQL workers use `FOR UPDATE SKIP LOCKED`; expired leases are reclaimable. Delivery atomically appends to `platform_event_log` and marks the outbox row `PUBLISHED`. The event log has a unique outbox reference, making replay idempotent. Failed attempts use bounded exponential delay and move to `DEAD_LETTER` after the configured attempt limit.

## APIs

- `GET /api/v1/outbox/summary`
- `GET /api/v1/outbox/events`
- `POST /api/v1/outbox/workers/run-next`
- `POST /api/v1/outbox/events/{event_id}/replay`
- `GET /api/v1/outbox/transport-receipts`
- `POST /api/v1/outbox/kafka/workers/run-next`
- `POST /api/v1/outbox/transport-receipts/{receipt_id}/replay`
- `GET /api/v1/events/log?after_sequence={sequence}`
- `GET /api/v1/events/stream` with `Last-Event-ID` for resumable SSE
- `POST /api/v1/event-stream-bindings`
- `POST /api/v1/event-stream-bindings/{binding_id}/route`
- `POST /api/v1/event-stream-bindings/{binding_id}/enqueue`
- `GET /api/v1/event-stream-bindings/{binding_id}/receipts`

Project-owned event-stream bindings bridge the durable platform event log into ordinary streams. Topic, event-type, aggregate-type, and ontology object-type filters are persisted with a cursor. Routing writes the event envelope, exact delivery receipt, stream sequence, and cursor in one transaction. The `event.stream.route` worker provides leased retry; PostgreSQL binding locks fence concurrent routers. This makes ontology changes directly consumable by event-time processors without weakening the outbox transaction boundary.

The internal event log remains the deterministic default transport. Kafka and Redpanda-compatible brokers are an independent second delivery stage. Each broker destination has a durable `event_transport_receipts` record with its own lease, attempts, retry schedule, dead-letter state, delivery timestamp, partition, offset, and stable event identity. Domain mutation code never calls a broker directly.

Configure `EVENT_KAFKA_BOOTSTRAP_SERVERS` and add `event.kafka.dispatch` to a worker's capabilities. Production defaults to `SASL_SSL`; plaintext requires the explicit `EVENT_KAFKA_ALLOW_PLAINTEXT=true` exception. SASL username and password, mechanism, topic prefix, request timeout, and max block time are configurable through the `EVENT_KAFKA_*` settings in `.env.production.example`.

Run the real-broker happy-path rehearsal after starting the repository Kafka profile:

```powershell
docker compose --profile cdc up -d zookeeper kafka
python oms/rehearse_event_kafka.py
```

The staged `oms/rehearse_event_kafka_recovery.py` command verifies broker interruption, persisted retry state, restart, replay, and final broker offset evidence. Its `prepare`, `interrupt`, `recover`, and `cleanup` stages are deliberately separate so operators can stop and restart the actual broker between stages.

## Recovery Invariants

- Domain rollback removes its audit/Ops or object-change evidence and outbox intent together.
- A crash after claim leaves an expiring visible lease.
- A failure before or after event-log insertion cannot leave a partial publication because insertion and status transition share one transaction.
- Replaying a published outbox row does not duplicate the durable event log.
- Dead-letter replay is explicit, permission checked, and auditable through persisted attempt/error state.
- A broker acknowledgement followed by a database failure may be delivered more than once; every attempt carries the same deterministic event ID so consumers can deduplicate safely.
- Project snapshots preserve outbox intents, internal event-log sequences, external delivery receipts, event-stream bindings, routing cursors, and exact stream receipts. In-flight leases restore as retryable work.
