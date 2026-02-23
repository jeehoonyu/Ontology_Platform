-- Enable GiST indices for overlapping temporal bounds
CREATE EXTENSION IF NOT EXISTS btree_gist;

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
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_type_id VARCHAR NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR DEFAULT 'PENDING',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
