-- Enable GiST indices for overlapping temporal bounds
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS postgis;

-- We track temporal boundaries via tstzrange (timestamp with time zone ranges)
-- Bitemporal means tracking both System Time (transaction_time) and Valid Time (business_time)

CREATE TABLE IF NOT EXISTS object_state (
    object_id VARCHAR NOT NULL,
    object_type_id VARCHAR NOT NULL,
    properties JSONB NOT NULL,
    
    -- Temporal constraints
    business_time TSTZRANGE NOT NULL,
    transaction_time TSTZRANGE DEFAULT tstzrange(CURRENT_TIMESTAMP, 'infinity'),

    -- Ensure we never have overlapping business_time entries for the exact same object
    CONSTRAINT no_overlapping_business_time EXCLUDE USING gist (
        object_id WITH =,
        business_time WITH &&
    )
);

-- Note: In a physical bitemporal model, you also want a constraint that transaction_time 
-- doesn't overlap for the same semantic business_time change, but for simplicity of this design
-- and to keep updates fast for the Action Execution Engine, we rely heavily on the outbox pattern.

-- Transactional Outbox Pattern Table
CREATE TABLE IF NOT EXISTS action_outbox (
    id VARCHAR PRIMARY KEY,
    action_type_id VARCHAR NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR DEFAULT 'PENDING',
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key VARCHAR PRIMARY KEY,
    action_type_id VARCHAR NOT NULL,
    response_payload JSONB,
    created_at INTEGER
);

-- Optional native PostGIS mirror for production-scale spatial indexing. The
-- FastAPI reference implementation stores GeoJSON in ontology JSON properties,
-- but this table can be populated by CDC/materialization jobs when spatial
-- queries need database-native GiST indexes.
CREATE TABLE IF NOT EXISTS ontology_geometries (
    object_id VARCHAR PRIMARY KEY,
    object_type_id VARCHAR NOT NULL,
    geometry GEOMETRY(GEOMETRY, 4326) NOT NULL,
    properties JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ontology_geometries_geom_idx
ON ontology_geometries
USING GIST (geometry);
