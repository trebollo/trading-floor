# Especificación: Research Lab (Laboratorio de Estrategias)

*Guardarraíles transversales: ver [00-marco-guardarrailes.md](00-marco-guardarrailes.md).
Aquí solo lo específico del departamento.*

## 1. Misión y alcance

Generar, formalizar y priorizar hipótesis de trading algorítmico, y entregarlas a
Backtest como especificaciones ejecutables y reproducibles. **No evalúa** sus propias
ideas: propone; el pipeline decide.

## 2. Agentes

### 2.1 `research-hypothesis` (×2)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Convertir contexto (directrices, lecciones, regímenes, post-mortems) en hipótesis formalizadas |
| Modelo | Generativo `frontier-strong` + `decisions: jev` para puntuación y dedup |
| Herramientas (G1) | `query_market_data` (solo OHLCV histórico), `run_python_sandbox` (sin red), `search_memory` (lecciones/evaluaciones), `read_directives` |
| Publica | `strategy.proposal.v1` |
| Consume | `directive.new`, `lesson.new`, `macro.regime.v1`, `backtest.report.v1` (feedback), `postmortem.report.v1` |

Salida obligatoria de cada propuesta: hipótesis económica (≤ 2 frases), universo y
timeframe, señales de entrada/salida formales, riesgo estimado a priori, lecciones
citadas que sustentan la idea (con id de evaluación).

### 2.2 `research-coder` (×2)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Convertir la propuesta en `strategy.spec.v1` (JSON Schema estricto) + código candidato para el motor |
| Modelo | Generativo `frontier-strong` |
| Herramientas (G1) | `strategy_api_docs`, `validate_spec` (validador de esquema local), `run_python_sandbox` |
| Publica | `strategy.spec.v1` |

El código candidato vive en un DSL restringido del motor (no Python arbitrario en
producción); el sandbox de Python es solo para exploración de la hipótesis.

### 2.3 `research-curator` (×1)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Priorizar la cola de propuestas, deduplicar, asignar presupuesto de investigación y de cómputo por propuesta |
| Modelo | Generativo `frontier-lite` + `decisions: jev` |
| Herramientas (G1) | `search_memory`, `read_evaluations`, `read_queue_state`, `publish_priority` |

## 3. Guardarraíles específicos

| # | Guardarrail | Tipo |
|---|---|---|
| R-1 | **Sandbox sin red y sin secretos** para `run_python_sandbox`; tiempo de CPU y memoria limitados | G6 |
| R-2 | **Anti look-ahead automático:** el validador de especificaciones rechaza toda señal que use datos no disponibles a la marca temporal de decisión (análisis estático del spec) | G5 |
| R-3 | **Cuota de propuesta:** máx. 20 hipótesis nuevas/día por agente de hipótesis (anti-dilución); el curator puede reasignar cuota según directrices | G5 |
| R-4 | **Deduplicación obligatoria** vía Jev contra el índice de memoria antes de publicar; similitud alta con propuesta ya rechazada ⇒ no se publica, se registra el motivo | G5 |
| R-5 | **Regla de familia bloqueada:** si una familia de estrategias (mismo patrón+universo+timeframe) falla validación 3 veces, queda bloqueada y solo una directriz del CEO la reabre | G5/G7 |
| R-6 | **Citación verificable:** toda lección invocada en el rationale debe existir y referenciar una evaluación real; las citas inexistentes se rechazan como alucinación (V2) | G5 |
| R-7 | **Reproducibilidad:** toda exploración en sandbox registra semilla, rango de datos y versión del dataset; propuesta sin registro reproducible ⇒ inválida | G5 |
| R-8 | **No acceden** a posiciones, órdenes, P&L en vivo ni credenciales de nada (solo histórico cerrado) | G4 |
| R-9 | Presupuesto: 2 M tokens/día por agente de hipótesis; al agotarse, el curator decide qué reencola | G3 |

## 4. Modos de fallo y degradación

- **Memoria no disponible:** el agente de hipótesis deja de proponer (fail-closed: proponer
  sin memoria es repetir errores pasados); el curator avisa.
- **Jev caído:** la deduplicación pasa a umbral determinista (similaridad coseno) y las
  propuestas dudosas se marcan `NEEDS_REVIEW` en vez de descartarse.
- **Agente de código sin presupuesto:** las propuestas se acumulan en cola; nunca se
  redactan specs "a medias" para cumplir cuota.

## 5. KPIs del departamento

Hipótesis publicadas/semana · tasa de aceptación en backtest · tasa de promoción a
producción · coste por hipótesis promovida · % de propuestas rechazadas por R-2/R-4/R-6
(indicador de calidad de generación) · cobertura de directrices del CEO.
