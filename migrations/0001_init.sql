-- Fase 0: esquema de la memoria colectiva (Postgres + TimescaleDB + pgvector).
-- Referencia: docs/arquitectura.md §5.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Ciclo de vida de estrategias
-- ---------------------------------------------------------------------------

CREATE TYPE strategy_status AS ENUM (
    'PROPUESTA', 'EN_BACKTEST', 'VALIDADA', 'APROBADA', 'PAPEL', 'VIVA', 'RETIRADA', 'BLOQUEADA'
);

CREATE TABLE strategies (
    id UUID PRIMARY KEY,
    spec_json JSONB NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status strategy_status NOT NULL DEFAULT 'PROPUESTA',
    owner_agent TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE evaluations (
    id UUID PRIMARY KEY,
    strategy_id UUID NOT NULL REFERENCES strategies (id),
    kind TEXT NOT NULL,                -- backtest | validation | risk_review
    result_json JSONB NOT NULL,
    verdict TEXT NOT NULL,
    report_uri TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Memoria de aprendizaje (episódica y semántica)
-- ---------------------------------------------------------------------------

CREATE TABLE lessons (
    id UUID PRIMARY KEY,
    content TEXT NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}',
    source_evaluation_id UUID REFERENCES evaluations (id),
    embedding vector(1536),            -- dimensión a fijar con el modelo de embeddings
    times_referenced INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX lessons_embedding_idx ON lessons USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Directrices del CEO
-- ---------------------------------------------------------------------------

CREATE TABLE directives (
    id UUID PRIMARY KEY,
    ceo_id TEXT NOT NULL,
    text TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'VIGENTE',
    effective_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Operativa (series temporales)
-- ---------------------------------------------------------------------------

CREATE TABLE orders (
    id UUID PRIMARY KEY,
    request_id TEXT NOT NULL,
    strategy_id UUID REFERENCES strategies (id),
    instrument TEXT NOT NULL,
    side TEXT NOT NULL,
    size DOUBLE PRECISION NOT NULL,
    risk_token TEXT,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE positions (
    id UUID PRIMARY KEY,
    strategy_id UUID REFERENCES strategies (id),
    instrument TEXT NOT NULL,
    size DOUBLE PRECISION NOT NULL,
    avg_price DOUBLE PRECISION NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE fills (
    id UUID PRIMARY KEY,
    order_id UUID NOT NULL REFERENCES orders (id),
    instrument TEXT NOT NULL,
    side TEXT NOT NULL,
    size DOUBLE PRECISION NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE risk_checks (
    id UUID PRIMARY KEY,
    order_id UUID REFERENCES orders (id),
    verdict TEXT NOT NULL,
    reason TEXT NOT NULL,
    technical BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Series temporales de mercado y métricas (TimescaleDB)
-- ---------------------------------------------------------------------------

CREATE TABLE market_data (
    ts TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    field TEXT NOT NULL,               -- open | high | low | close | volume | feature:*
    value DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (ts, symbol, field)
);

SELECT create_hypertable('market_data', 'ts', IF_NOT_EXISTS => TRUE);

CREATE TABLE signals (
    ts TIMESTAMPTZ NOT NULL,
    strategy_id UUID NOT NULL,
    symbol TEXT NOT NULL,
    signal_json JSONB NOT NULL,
    PRIMARY KEY (ts, strategy_id, symbol)
);

SELECT create_hypertable('signals', 'ts', IF_NOT_EXISTS => TRUE);

CREATE TABLE regime_history (
    ts TIMESTAMPTZ NOT NULL,
    regime TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    stale BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (ts, regime)
);

SELECT create_hypertable('regime_history', 'ts', IF_NOT_EXISTS => TRUE);

-- ---------------------------------------------------------------------------
-- Audit log inmutable con hash encadenado (la referencia del sistema)
-- ---------------------------------------------------------------------------

CREATE TABLE audit_log (
    seq BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);

-- Apéndice-only: sin UPDATE ni DELETE ni siquiera para el propietario de la tabla.
CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;
