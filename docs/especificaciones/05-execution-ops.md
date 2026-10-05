# Especificación: Execution & Ops Department

*Guardarraíles transversales: ver [00-marco-guardarrailes.md](00-marco-guardarrailes.md).*

## 1. Misión y alcance

Ejecutar exactamente las órdenes autorizadas por Risk, contabilizar los resultados y
operar la salud de la infraestructura de trading. Único departamento con acceso a
brokers/exchanges.

## 2. Agentes

### 2.1 `execution-router` (×1)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Convertir `risk.decision.v1` en órdenes de broker (algoritmo: marketable limit, TWAP simple, splitting por volumen), gestionar parciales, reintentos y cancelaciones |
| Modelo | **Determinista.** Sin LLM en el camino de la orden |
| Herramientas (G1) | `broker_*` (place, cancel, replace, query) — únicas del sistema, `verify_risk_token`, `read_strategy_contract` |
| Publica | `order.status.v1`, `fill.v1`, `execution.exception.v1` |

### 2.2 `ops-monitor` (×1)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Salud del sistema: latencias, fallos de feeds, colas atascadas, discrepancias de posición (reconciliación con el broker cada 5 min) |
| Modelo | Generativo `frontier-lite` + `decisions: jev` (clasificación de incidentes) |
| Herramientas (G1) | `read_system_metrics`, `read_broker_positions`, `read_internal_positions`, `publish_incident`, `trigger_kill_switch` (departamental y global) |
| Publica | `ops.incident.v1`, `ops.reconciliation.v1` |

### 2.3 `ops-bookkeeper` (×1)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Registro contable de fills, P&L realizado/no realizado, alimentación de la memoria de series |
| Modelo | Determinista |
| Herramientas (G1) | `append_ledger` (append-only), `read_fills` |
| Publica | `ledger.entry.v1` |

## 3. Guardarraíles específicos

| # | Guardarrail | Tipo |
|---|---|---|
| E-1 | **Monopolio de credenciales de broker:** solo `execution-router` las posee, en el contenedor, inyectadas como secreto; jamás en prompts, contexto ni memoria | G6 |
| E-2 | **Verificación de `risk_token`:** toda orden se valida contra el token firmado (identidad, tamaño, expiración) antes de tocar el broker; token inválido o expirado ⇒ rechazo y alerta a Risk | G5 |
| E-3 | **Whitelist de instrumentos:** solo instrumentos del universo autorizado por el CEO; el router verifica contra la lista, no contra el mensaje | G5 |
| E-4 | **Stop obligatorio:** si el contrato de la estrategia exige stop, la orden de entrada sin su stop asociado no se envía (se construyen juntas o nada) | G5 |
| E-5 | **Idempotencia total:** `client_order_id` determinista por (orden, intento lógico); un reintento nunca duplica posición | G5 |
| E-6 | **Límites de frecuencia:** máx. órdenes/minuto por estrategia y global (defecto en config); proteger el broker y detectar bucles | G5 |
| E-7 | **Kill switch local:** el router y el monitor pueden auto-suspenderse ante anomalías (rechazos del broker repetidos, latencia anómala, desvío de posición > umbral) | G5/G7 |
| E-8 | **Reconciliación autoridad:** si el broker dice una posición y el ledger interno dice otra, prevalece el broker para límites de riesgo hasta resolver; incidente V4 | G7 |
| E-9 | **Sin decisiones de negocio:** este departamento no decide qué operar ni cuánto; ejecuta y reporta. Un LLM suyo nunca ve ni puede pedir contextos de otras áreas | G4 |
| E-10 | **Horarios y estados del mercado:** no se envían órdenes fuera de sesiones válidas ni durante halts; verificación determinista por calendario | G5 |

## 4. Modos de fallo y degradación

- **Broker caído o rechazos sistemáticos:** auto-suspensión del router (E-7), modo
  solo-cierre, incidente al CEO si dura > X min.
- **Feed de mercado degradado:** Ops puede declarar `DATA_DEGRADED`; Risk aplica peor
  caso; Execution no inicia aperturas nuevas.
- **Bookkeeper caído:** el router sigue operando (los fills llegan al bus); el ledger se
  reconstruye por replay del bus — por eso todo pasa por eventos.

## 5. KPIs del departamento

Slippage realizado vs. esperado por orden · tasa de rechazos de broker · tiempo de
detección y resolución de discrepancias · órdenes por minuto pico · exactitud del ledger
(auditado contra el broker mensualmente).
