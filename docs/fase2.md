# Fase 2 — Riesgo y ejecución en papel (implementada)

Gate pre-trade determinista, contratos de riesgo, tokens firmados, execution router en
papel, ledger con replay y reconciliación. Según
[docs/especificaciones/04-risk.md](especificaciones/04-risk.md) y
[05-execution-ops.md](especificaciones/05-execution-ops.md).

## Qué hay

| Pieza | Módulo | Guardarraíles que implementa |
|---|---|---|
| `RiskLimits` (config del CEO) | `src/tf/risk.py` | K-5: versión declarativa, doble confirmación fuera de código |
| `StrategyContract` por estrategia | `src/tf/risk.py` | §6: tamaño máx., universo, stop obligatorio, DD propio, restricción de régimen |
| Tokens de riesgo HMAC con TTL | `src/tf/risk.py` | K-3: firmados, expiración 60 s, verificación defensiva |
| `PreTradeGate` determinista | `src/tf/risk.py` | K-1/K-2/K-4: fail-closed, sin LLM, reduce antes de rechazar |
| Modo solo-cierre automático | `src/tf/risk.py` | DD diario/total superado ⇒ solo cierres, nunca aperturas |
| `PaperBroker` + `ExecutionRouter` | `src/tf/execution.py` | E-1/E-2/E-5/E-6/E-7/E-9: clampa al token, idempotencia, frecuencia, auto-suspensión |
| `Ledger` + `reconcile` | `src/tf/execution.py` | E-8: broker manda; reconstrucción por replay de eventos |
| Demo del día de trading | `scripts/run_trading_day.py` | 9 escenarios con guardarraíles activos |

## Semántica de decisión del gate

- `AUTORIZADA` — cumple todo; emite token por el tamaño pedido.
- `REDUCIR` — autorizada con tamaño recortado al mínimo de: contrato, riesgo por
  operación y hueco de exposición. El router **ejecuta al tamaño del token** (clamped),
  nunca por encima.
- `RECHAZADA` — veto (universo, stop ausente, régimen, límites agotados) o fallo técnico.
  Los rechazos técnicos (`technical=True`) delatan estado ausente: fail-closed (K-2).
- **Cerrar siempre se permite** (incluso en modo solo-cierre): cerrar reduce riesgo, así
  que no lleva caps de tamaño.

## Verificación

81 tests en total (`uv run pytest -q`), incluidos:

- tokens: roundtrip, expiración, firma manipulada, secreto incorrecto;
- gate: fail-closed sin contrato/estado, universo, stop obligatorio, régimen adverso en
  contratos provisionales, reducción por riesgo/exposición, drawdown diario y total con
  modo solo-cierre que aún permite cerrar;
- router: token inválido/expirado/no correspondiente (y cuentan para auto-suspensión),
  idempotencia de `request_id`, límite de frecuencia con liberación tras el minuto,
  rechazos de broker ⇒ suspensión, clamp de REDUCIR;
- ledger/reconciliación: replay de posiciones desde eventos y detección de fills
  fantasma del broker.

Demo (`uv run python scripts/run_trading_day.py`): los 9 escenarios anteriores — stop
ausente rechazado, REDUCIR ejecutado al tamaño del token, universo cerrado, id
duplicado bloqueado por E-5, crash que activa solo-cierre, cierre permitido en
solo-cierre, token expirado rechazado, reconciliación limpia.

## Límites conocidos

- Broker solo de papel; adaptadores reales (IBKR, ccxt, etc.) se enchufan tras la
  interfaz de `PaperBroker` en Fase 4.
- El estado del portfolio se pasa como snapshot (`PortfolioState`); en integración real
  lo materializa la plataforma desde el ledger y las cotizaciones (mismo esquema).
- La firma HMAC usa un secreto en memoria; en producción vendrá del gestor de secretos.

## Siguientes pasos (Fase 3)

Memoria y evolución: lecciones aprendidas automáticas de evaluaciones y rechazos,
post-mortems de estrategias retiradas, curator con memoria semántica (pgvector),
drift detection semanal y revisión de portfolio.
