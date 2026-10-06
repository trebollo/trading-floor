-- Estado operacional compartido por runners de contenedores.
CREATE TABLE IF NOT EXISTS tf_state (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    version BIGINT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
