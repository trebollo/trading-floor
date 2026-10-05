# Fase 1 — Pipeline de investigación (implementada)

Ciclo **Research → Backtest → Validation** end-to-end, 100 % determinista, con la batería
canónica completa. Los agentes de Research son plantillas; en Fase 2 se sustituyen por
LLM sin cambiar contratos ni guardarraíles.

## Qué hay

| Pieza | Módulo | Notas |
|---|---|---|
| Datos sintéticos con regímenes + cargador CSV | `src/tf/marketdata.py` | Determinista (R-7); sin red |
| DSL restringido de estrategias | `src/tf/dsl.py` | Lista blanca: `sma_cross`, `breakout`, `rsi_reversion`, `momentum`; máx. 6 parámetros (anti-sobreajuste) |
| Motor de backtest vectorizado | `src/tf/engine.py` | Ejecución en barra siguiente (anti-look-ahead por construcción); costes fraccionales por cambio de posición; métricas CAGR/Sharpe/maxDD/profit factor/trades/exposición |
| Batería canónica (6 puntos) | `src/tf/validation.py` | Monte Carlo (permutación + bootstrap de bloques), walk-forward, estrés de régimen, sensibilidad ±20 %, costes ×2, correlación con portfolio |
| Pipeline orquestado sobre el bus | `src/tf/pipeline.py` | `research-hypothesis` publica propuestas, `research-coder` formaliza specs (permisos separados, G1), `PipelineRunner` evalúa y audita |
| Demo end-to-end | `scripts/run_pipeline.py` | Catálogo JSON + audit log íntegro |

## Resultado del demo (datos sintéticos, 2.000 barras)

- `momentum 60/0.02` → **VALIDADA**: 6/6 en la batería (MC p5 retorno +527 %, WF ratio
  0.76, sensibilidad sin cliff, costes ×2 soportados).
- `rsi_reversion` (contra-tendencia) → **RECHAZADA_BACKTEST** (retorno -29 %, DD 48 %).
- `sma_cross 60/20` (ventanas invertidas) → **RECHAZADA_SPEC** por el validador del DSL.
- `sma_cross 20/60` y `breakout 50` → **RECHAZADA_BACKTEST** por B-4 (menos de 30
  operaciones: no hay evidencia estadística suficiente).

## Bugs que los tests destaparon durante el desarrollo

1. **Desalineación de retornos**: la posición cobraba el retorno de la barra *anterior* a
   su entrada. Corregido: la posición efectiva \(i\) cobra open \(i \to i{+}1\).
2. **Costes en unidades absolutas**: multiplicar por el precio y restar a retornos
   fraccionales destruía el equity. Corregido: costes fraccionales.
3. **Régimen adverso simétrico**: el generador producía un mercado bajista 50 % del
   tiempo. Corregido: fases adversas cortas (~9 %), como crisis reales.

## Límites conocidos

- **Sin infra en el orb**: no hay daemon de Docker aquí, así que los adaptadores NATS
  JetStream y `AuditLog` en Postgres quedan pendientes de integración real (las
  interfaces ya están fijadas y el hash encadenado probado en SQLite).
- **Sin datos reales**: el cargador CSV está listo; falta conectar una fuente de mercado.
- **Research en plantillas**: la generación por LLM llega en Fase 2 vía Model Gateway.

## Tests

55 tests en total (`uv run pytest -q`), incluidos:
- anti-look-ahead: alterar el futuro no cambia el equity pasado;
- costes solo reducen (nunca aumentan) el retorno;
- Monte Carlo determinista con semilla y rechazo de esperanza negativa;
- walk-forward con degradación razonable en tendencia;
- la batería rechaza specs inválidos, mercados sin evidencia y esperanza negativa;
- permisos: cada rol solo publica sus tipos de mensaje.

## Siguientes pasos (Fase 2)

Gate pre-trade determinista + contratos de riesgo + execution router (paper) +
reconciliación, según [docs/especificaciones/04-risk.md](especificaciones/04-risk.md)
y [05-execution-ops.md](especificaciones/05-execution-ops.md).
