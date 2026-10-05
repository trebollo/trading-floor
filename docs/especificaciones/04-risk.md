# Especificación: Risk Department (Comité de Riesgos)

*Guardarraíles transversales: ver [00-marco-guardarrailes.md](00-marco-guardarrailes.md).*

## 1. Misión y alcance

Última barrera antes de operar. Autoriza o rechaza **toda** orden y **todo** despliegue de
estrategia, vigila el riesgo agregado del portfolio y ejecuta los modos de defensa.
Si algo no cumple, no es válido: su veto solo lo anula el CEO, y solo en despliegues,
nunca en órdenes en vivo.

## 2. Agentes

### 2.1 `risk-pretrade` (servicio + LLM de explicación)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Gate en línea: responder a cada `order.request.v1` con `AUTORIZADA(tamaño_máximo) | REDUCIR | RECHAZADA(motivo)` y emitir un `risk_token` firmado con TTL |
| Modelo | **Núcleo determinista** (código firmado); LLM `frontier-lite` solo para redactar el motivo legible; Jev pre-puntúa rubrics pero nunca decide |
| Herramientas (G1) | `read_limits`, `read_portfolio_state`, `read_strategy_contract`, `emit_risk_token` |
| Publica | `risk.decision.v1` (con `risk_token`), `risk.rejection.v1` |

SLA: p99 < 50 ms en modo determinista. **Fail-closed:** si no puede evaluar (datos
ausentes, timeout), responde `RECHAZADA(RAZON_TECNICA)`.

### 2.2 `risk-portfolio` (×1)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Riesgo agregado: exposición por activo/sector/divisa, drawdown, correlaciones en vivo, VaR/ES, propongo ajustes de tamaño y modos de defensa |
| Modelo | Generativo `frontier-lite` + `decisions: jev` (pre-puntuación de rubrics) |
| Herramientas (G1) | `read_portfolio_state`, `read_market_data`, `read_limits`, `read_strategy_contracts`, `propose_defense_mode`, `publish_review` |
| Publica | `risk.portfolio_review.v1`, `risk.defense_mode.v1`, `risk.limit_breach.v1` |

## 3. Límites duros (configurables solo por el CEO, doble confirmación)

- Riesgo por operación: ≤ 1 % del capital (defecto 0,5 %).
- Exposición máxima por activo, sector, divisa y dirección.
- Drawdown diario/semanal/total → reducción automática de tamaño; superado el total ⇒
  modo solo-cierre automático.
- Máximo de posiciones correlacionadas (ρ > 0.7 misma dirección).
- Apalancamiento máximo global.
- Vetos absolutos: nada fuera del universo autorizado, nada sin stop donde el contrato lo
  exija, ninguna estrategia sin contrato de riesgo firmado, ninguna orden sin `risk_token`.

## 4. Guardarraíles específicos

| # | Guardarrail | Tipo |
|---|---|---|
| K-1 | **El gate es código firmado:** el núcleo de decisión pre-trade se despliega solo por pipeline de plataforma con firma; ningún agente ni despliegue ad-hoc puede modificarlo | G6 |
| K-2 | **Fail-closed universal:** cualquier dato ausente, timeout o inconsistencia ⇒ rechazo técnico; nunca autorización por defecto | G5 |
| K-3 | **risk_token firmado con TTL:** cada orden autorizada lleva token firmado (orden, tamaño máximo, estrategia, expiración ≤ 60 s). Execution verifica la firma; sin token o expirado ⇒ rechazo | G5/G6 |
| K-4 | **Los agentes de Risk no autorizan:** ni Jev ni el LLM emiten autorizaciones; como mucho marcan flags y redactan motivos. La autorización es aritmética contra límites, no opinión | G5 |
| K-5 | **Inmutabilidad de límites:** los límites viven en configuración versionada; cualquier cambio exige identidad del CEO + doble confirmación + registro; los agentes solo los leen | G7 |
| K-6 | **Modo defensa con límites propios:** `risk-portfolio` puede *proponer* y activar modos de defensa predefinidos (reducir aperturas, apretar stops, solo-cierre) definidos por el CEO; no puede inventar modos nuevos ni reabrir posiciones | G5 |
| K-7 | **Veto no anulable por agentes:** ningún mensaje de ningún departamento puede revocar un rechazo de riesgo; solo la vía del CEO para despliegues | G5/G7 |
| K-8 | **Replay semanal de consistencia:** se re-ejecutan las decisiones de la semana contra la versión actual del gate; divergencias se reportan al CEO | auditoría |
| K-9 | **Aislamiento de optimización:** Risk no recibe objetivos de P&L ni incentivos de beneficio; sus métricas internas son solo de control (brechas evitadas, falsos rechazos calibrados) | G5 |

## 5. Modos de fallo y degradación

- **Gate caído:** no hay órdenes nuevas en todo el sistema (Execution entra en
  solo-cierre). El trading se detiene; no se degrada a "confiar".
- **LLM de explicación caído:** las decisiones siguen (el motivo legible se genera luego
  o queda como código de motivo); la latencia del gate nunca depende del LLM.
- **Datos de mercado incompletos para calcular exposición:** se aplica el peor caso
  (exposición máxima asumida) hasta reconciliación.

## 6. KPIs del departamento

Latencia p99 del gate · tasa de falsos rechazos (órdenes rechazadas que habrían sido
beneficiosas — se mide en papel) · brechas de límite evitadas · tiempo de detección de
brechas · drfit entre decisiones y replay semanal.
