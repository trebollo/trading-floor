# Trading Floor

Sistema multiagente de trading algorítmico autónomo, organizado como una empresa digital:
departamentos especializados que se comunican por un bus de eventos, con riesgo como
barrera absoluta y el CEO como única autoridad humana de gobierno.

## Documentación

- [Arquitectura del sistema](docs/arquitectura.md) — diseño completo: departamentos,
  agentes, comunicación, memoria colectiva, ciclo de vida de una estrategia, stack,
  hoja de ruta y KPIs.

## Resumen en una frase

Agentes de IA proponen estrategias; un pipeline determinista (backtest → validación
Monte Carlo/walk-forward → comité de riesgos) decide qué sobrevive; el portfolio se opera
automáticamente dentro de límites duros, y todo queda registrado en una memoria colectiva
auditable que alimenta el siguiente ciclo de investigación.

## Departamentos

| Departamento | Función |
|---|---|
| Dirección (Executive Suite) | Directrices del CEO, informes, presupuestos |
| Research Lab | Generación de hipótesis y especificaciones de estrategias |
| Backtest Dept | Evaluación histórica objetiva con costes realistas |
| Validation Dept | Monte Carlo, walk-forward, estrés de regímenes, adversario dedicado |
| Risk Dept | Gate pre-trade y riesgo de portfolio; veto absoluto |
| Execution & Ops | Ejecución de órdenes, reconciliación, contabilidad |
| Macro & News | Regímenes de mercado, noticias, calendario económico |

Los modelos de cada agente son **intercambiables por configuración** a través de un Model
Gateway. Para las decisiones estructuradas (triaje, clasificación, puntuación de rubrics)
se usa **Jev** (`typesafe-ai/jev`, modelo de evaluación de TypeSafe AI vía Vercel AI
Gateway): rápido, ~$0.042/M tokens y sin generación de texto; la redacción corre a cargo de
modelos generativos ligeros por rol (ver
[docs/arquitectura.md §7.1](docs/arquitectura.md#71-capa-de-modelos-intercambiables-model-gateway)).

## Estado

Fase de diseño.

- **[Arquitectura general](docs/arquitectura.md)** — visión, departamentos, comunicación,
  memoria colectiva, stack y hoja de ruta.
- **[Marco de guardarraíles](docs/especificaciones/00-marco-guardarrailes.md)** y
  **especificación por departamento**:
  [Research Lab](docs/especificaciones/01-research-lab.md) ·
  [Backtest](docs/especificaciones/02-backtest.md) ·
  [Validation](docs/especificaciones/03-validation.md) ·
  [Risk](docs/especificaciones/04-risk.md) ·
  [Execution & Ops](docs/especificaciones/05-execution-ops.md) ·
  [Macro & News](docs/especificaciones/06-macro-news.md) ·
  [Dirección](docs/especificaciones/07-direccion.md).

Hoja de ruta de implementación: [docs/arquitectura.md §10](docs/arquitectura.md#10-hoja-de-ruta-por-fases).

## Implementación

- **Fase 0 (cimientos)** — implementada y testeada. Ver [docs/fase0.md](docs/fase0.md):
  contratos de mensajes, bus con validación en el borde, Permission Broker, Model
  Gateway, esqueleto de agentes y audit log con hash encadenado.
- **Fase 1 (pipeline de investigación)** — implementada y testeada. Ver
  [docs/fase1.md](docs/fase1.md): DSL restringido, motor de backtest anti-look-ahead,
  batería canónica completa (Monte Carlo, walk-forward, régimen, sensibilidad, costes,
  correlación) y catálogo de estrategias evaluadas end-to-end.
- **Fase 2 (riesgo y ejecución en papel)** — implementada y testeada. Ver
  [docs/fase2.md](docs/fase2.md): gate pre-trade determinista fail-closed, tokens de
  riesgo HMAC con TTL, contratos de estrategia, modo solo-cierre por drawdown, execution
  router con idempotencia y auto-suspensión, ledger con replay y reconciliación.
- **Fase 3 (memoria y evolución)** — implementada y testeada (94 tests). Ver
  [docs/fase3.md](docs/fase3.md): lecciones automáticas por modo de fallo, memoria
  consultable con deduplicación semántica, bloqueo de familias (R-5), drift detection
  con retiro automático por contrato, post-mortems y comité semanal.

```bash
uv sync && uv run pytest -q                  # 94 tests
uv run python scripts/run_pipeline.py        # demo Fase 1: investigación
uv run python scripts/run_trading_day.py     # demo Fase 2: día de trading en papel
uv run python scripts/run_evolution.py       # demo Fase 3: evolución y aprendizaje
```
