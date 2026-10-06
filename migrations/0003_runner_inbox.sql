-- Recibos idempotentes para consumers durables (JetStream entrega al menos una vez).
CREATE TABLE IF NOT EXISTS tf_inbox (
    department TEXT NOT NULL,
    envelope_id TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (department, envelope_id)
);
CREATE INDEX IF NOT EXISTS tf_inbox_processed_at_idx ON tf_inbox (processed_at);
