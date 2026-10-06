-- Salidas persistentes de departamento pendientes de confirmación JetStream.
CREATE TABLE IF NOT EXISTS tf_outbox (
    event_id TEXT PRIMARY KEY,
    department TEXT NOT NULL,
    subject TEXT NOT NULL,
    envelope JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS tf_outbox_pending_idx
    ON tf_outbox (department, created_at)
    WHERE published_at IS NULL;
