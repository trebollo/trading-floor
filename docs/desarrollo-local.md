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
uv run python scripts/run_daily_cycle.py    # sistema vivo: ciclo diario completo
uv run python scripts/run_pipeline.py
uv run python scripts/run_paper_day.py --csv data/aapl.csv   # paper trading sobre datos reales
uv run python scripts/run_trading_day.py
uv run python scripts/run_evolution.py
```

## Datos reales (Yahoo Finance, sin API key)

```bash
uv run python scripts/ingest_data.py AAPL '^GSPC' --start 20150101   # → data/aapl.csv, data/^gspc.csv
uv run python scripts/run_pipeline.py --csv data/aapl.csv            # pipeline completo sobre datos reales
```

Los CSV quedan en `data/` (ignorado por git) en formato `ts,open,high,low,close` y se
validan (OHLC coherente) antes de escribirse. `tf.datafeed` es la única pieza que habla
con la red; el resto del sistema sigue leyendo vía `tf.marketdata.load_csv` (G4/B-6).

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

1. **Adaptador NATS de `tf.bus.BaseBus`** ✅ (`tf.bus_nats`)
2. **`AuditLog` en Postgres** ✅ (`tf.audit_pg`)
3. **Fuente de datos real** ✅ (`tf.datafeed` + `scripts/ingest_data.py`; descarga manual;
   la descarga periódica y el volcado a `market_data` vendrán con el planificador)
4. **Agentes LLM reales** ✅ parcial (`tf.gateway` con clientes HTTP reales: Jev y
   generativos, todo por OpenCode Zen con una sola key, `OPENCODE_API_KEY`;
   `ResearchLLMAgent` en Research). Exporta `OPENCODE_API_KEY` en tu entorno y ejecuta
   `uv run python scripts/run_pipeline.py --llm`. Sin credenciales, los agentes degradan
   a las plantillas deterministas y lo dejan auditado (`model.failover`).
5. **Broker adapter** — la interfaz de `PaperBroker` es el contrato; primero otro paper
   broker contra datos reales, luego el real con capital reducido.

## Fase 5: sistema vivo

`tf.scheduler.DailyCycle` orquesta el ciclo: ingesta (Yahoo) → research (LLM reales si
hay `OPENCODE_API_KEY`) → paper day con guardarraíles → memoria persistida
(`state/memory.json`) → comité semanal de drift (automático si ha pasado una semana;
`--force-weekly` lo fuerza). Una fase que falla queda auditada como `ops.incident` y el
ciclo continúa con el último dato válido. En tu Mac, con Docker arriba, usa NATS y
Postgres automáticamente; sin ellos, bus en memoria y audit SQLite.

## Notas

- No hay secretos en el repo: el `POSTGRES_PASSWORD` del compose es de desarrollo. Los
  secretos reales (broker, LLM) van en tu gestor local (`amp secrets` / variables de
  entorno al arrancar).
- El audit log de Postgres es apéndice-only por reglas SQL; las migraciones se aplican
  solas al crear el contenedor (`/docker-entrypoint-initdb.d`).
