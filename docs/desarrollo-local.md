# Desarrollo local (tu máquina, con Docker)

El orb de Amp no tiene daemon de Docker; las piezas de infraestructura (Postgres +
Timescale, NATS JetStream) se ejecutan localmente con el CLI de Amp.

## Requisitos

- Docker Desktop (o docker engine + compose v2)
- Python 3.12+ y [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

## Arranque

```bash
git clone https://github.com/trebollo/trading-floor && cd trading-floor

# 1) Infraestructura: Postgres+Timescale (con las migraciones) y NATS
docker compose up -d
docker compose ps                       # ambos "healthy/running"
# Postgres: localhost:5432 (trading/trading_floor) · NATS: localhost:4222, monitor 8222

# 2) Código y tests
uv sync
uv run pytest -q                        # 94 tests

# 3) Demos end-to-end
uv run python scripts/run_pipeline.py
uv run python scripts/run_trading_day.py
uv run python scripts/run_evolution.py
```

## Verificar la infra a mano

```bash
# Postgres: esquema cargado y audit log apéndice-only
docker compose exec postgres psql -U trading -d trading_floor -c "\dt"
docker compose exec postgres psql -U trading -d trading_floor \
  -c "INSERT INTO audit_log (actor, event_type, payload) VALUES ('x','y','{}'::jsonb) RETURNING seq, hash;"

# NATS: JetStream activado
curl -s http://localhost:8222/jsz | head
```

## Conectar el CLI local de Amp

Desde tu máquina, con `amp` instalado y logueado, puedes continuar este hilo o abrir un
hilo nuevo en el checkout local (`amp threads continue` desde el repo, o
`amp --continue`). El trabajo que hagan esos hilos corre en tu máquina: ahí sí pueden
hablar con `localhost:5432` y `localhost:4222`.

## Qué queda pendiente de la Fase 4 y en qué orden

1. **Adaptador NATS de `tf.bus.BaseBus`** — la interfaz ya está fijada; solo transporte.
2. **`AuditLog` en Postgres** — el hash encadenado ya está probado sobre SQLite.
3. **Fuente de datos real** — `tf.marketdata.load_csv` está listo; añadir descarga
   periódica (p. ej. proveedor de barras diarias) y volcado a `market_data`.
4. **Agentes LLM reales** — Model Gateway + proveedores (Jev para decisiones vía Vercel
   AI Gateway; generativos por rol) sustituyendo las plantillas de Research.
5. **Broker adapter** — la interfaz de `PaperBroker` es el contrato; primero otro paper
   broker contra datos reales, luego el real con capital reducido.

## Notas

- No hay secretos en el repo: el `POSTGRES_PASSWORD` del compose es de desarrollo. Los
  secretos reales (broker, LLM) van en tu gestor local (`amp secrets` / variables de
  entorno al arrancar).
- El audit log de Postgres es apéndice-only por reglas SQL; las migraciones se aplican
  solas al crear el contenedor (`/docker-entrypoint-initdb.d`).
