# Trading Floor — AGENTS.md

Sistema multiagente de trading algorítmico (Python + Next.js). docs/arquitectura.md es la fuente de verdad de diseño; docs/desarrollo-local.md y docs/especificaciones/08-containerizacion.md describen el despliegue actual. Código, docs y commits están **en español**.

## Commands

```bash
uv sync && uv run pytest -q          # suite completa
uv run pytest tests/test_risk.py -q  # un archivo; -k "nombre" para un test
docker compose up -d                 # Postgres+Timescale y NATS (solo en tu máquina; el orb de Amp NO tiene Docker)
uv run pytest -q -m infra            # solo integración con NATS/Postgres (auto-skip si no están)
docker compose --profile app run --rm tf-cycle       # ciclo monolítico paper (de transición)
docker compose --profile pipeline --profile manual run --rm tf-pipeline # ingesta + pipeline distribuido
docker compose --profile pipeline up -d              # workers + scheduler diario UTC (TF_SCHEDULE_UTC)
```

- Demos end-to-end: `uv run python scripts/run_daily_cycle.py` (sistema vivo completo), `run_pipeline.py`, `run_trading_day.py`, `run_paper_day.py --csv data/aapl.csv`, `run_evolution.py`. Añade `--llm` al pipeline para modelos reales (requiere `OPENCODE_API_KEY`).
- El perfil `pipeline` separa Research, Backtest, Validation, Macro/News y Executive; Backtest/Validation admiten queue groups. Risk/Execution paper siguen en `tf-cycle` con `InMemoryBus` y no están desplegados por separado. No habilites live ni réplicas de Risk/Execution sin outbox/ledger idempotente.
- Dashboard (`dashboard/`): app aparte, **pnpm**, Next.js 15 + React 19, puerto 3100. `pnpm install && pnpm dev`; verificación es `pnpm typecheck` (no hay tests JS). Con `DATABASE_URL` lee la DB real; sin ella, modo demo. Gestionada por Amp vía `.amp/services.yaml`.

## Architecture gotchas

- **Modelos = configuración** (`config/models.yaml`, servidos por OpenCode Zen/Go con una sola key `OPENCODE_API_KEY`). Nunca añadas providers LLM hardcodeados en agentes; van por `tf/gateway.py`. Sin credenciales los agentes **degradan a plantillas deterministas** con failover auditado (`model.failover`) — los tests no deben hacer nunca llamadas de red.
- **Fail-closed es ley**: toda orden pasa por el gate determinista de riesgo (`tf/risk.py`, K-1..K-4) vía bus; sin decisión de riesgo no hay ejecución. No relajes esto ni en tests/demos.
- Todo flujo de eventos es bus-driven con mensajes versionados (`strategy.spec.v1`, `risk.decision.v1`, ... en `tf/contracts.py`). El audit log es apéndice-only con cadena de hash (`tf/audit.py`, `tf/audit_pg.py`) — si lo tocas, verifica la cadena.
- `tf/datafeed.py` consulta Yahoo; `tf/news.py` también consulta GDELT, Finnhub y RSS. Mantén tests sin red (`news_config={}` o mocks). Los datasets distribuidos viajan como snapshots CSV con SHA-256.
- Presupuesto G3 (`tf/budget.py`): con Postgres usa `tf_state`; en modo local fallback conserva `state/budget_state.json`. `BudgetExceeded` degrada a ruta determinista, nunca reintenta.
- JetStream entrega al menos una vez. Los runners usan inbox persistente e IDs estables para el pipeline batch; no habilites live ni réplicas de Risk/Execution sin outbox/ledger idempotente.
- Guardarraíles y límites viven en `config/guardrails.yaml` + `config/directivas.yaml`; el scheduler aplica directivas vigentes al inicio de cada ciclo.

## Testing / env quirks

- Los tests de infra se saltan solos si NATS/Postgres no responden — en el orb todo corre con bus en memoria y audit SQLite (`state/audit.db`), no lo des por bug.
- GDELT bloquea IPs de datacenter (orbs); el news-analyst funciona solo en máquina local.
- El dashboard no tiene autenticación; Compose lo liga a loopback. No lo expongas ni lo uses para gobierno live.
- No hay secretos en el repo: `POSTGRES_PASSWORD` del compose es de desarrollo; credenciales reales van como env vars.
