# Trading Floor — Arquitectura del sistema multiagente de trading autónomo

**Versión:** 1.0 (diseño inicial)
**Fecha:** 2026-10-05
**Propietario:** CEO (Tomas Rebollo)

---

## 1. Visión y objetivos

Trading Floor es una organización digital autónoma de trading algorítmico, modelada como
una empresa real: departamentos especializados, agentes con roles, comunicación formal
entre áreas y una dirección humana (el CEO) que fija directrices y aprobar ajustes.

Objetivos medibles del sistema:

1. **Operar de forma autónoma** un portfolio de estrategias validadas, 24/7.
2. **Evolucionar continuamente**: generar, validar, desplegar y retirar estrategias sin
   intervención humana salvo en los puntos de gobierno definidos (§9).
3. **Maximizar el beneficio ajustado a riesgo**, no el beneficio bruto: toda decisión de
   negocio pasa por el filtro del Departamento de Riesgos.
4. **Auditoría total**: cada decisión relevante (una estrategia aprobada, una orden
   enviada, un rechazo de riesgo) queda registrada de forma inmutable y explicable.
5. **Memoria colectiva persistente**: el sistema aprende de sus aciertos y de sus errores
   entre sesiones, semanas y regímenes de mercado.

### Principios de diseño no negociables

| # | Principio | Consecuencia práctica |
|---|-----------|----------------------|
| P1 | **Los LLM proponen, el código determinista dispone** | La generación de ideas usa LLM; el backtest, la validación estadística, el gating de riesgo y la ejecución son código determinista y testeable. Ningún LLM coloca una orden directamente. |
| P2 | **Riesgo con veto absoluto** | El Departamento de Riesgos es el único con autoridad para bloquear cualquier operación o despliegue; su veto no puede ser anulado por otros agentes, solo por el CEO. |
| P3 | **Nada llega a mercado real sin gradiente de exposición** | Toda estrategia nueva recorre: backtest → validación avanzada → trading en papel → capital mínimo → capital completo. |
| P4 | **Memoria explícita, no implícita** | El aprendizaje vive en bases de datos versionadas, no en el contexto de los agentes. Los agentes son sin estado; el estado vive en la plataforma. |
| P5 | **Cada agente es reemplazable** | Los agentes son procesos sin estado que se conectan al bus; se pueden pausar, sustituir o actualizar sin parar el sistema. |
| P6 | **Kill switch en todo nivel** | Cada departamento, agente, estrategia y el sistema completo tienen un interruptor de parada con telemedida. |

---

## 2. Arquitectura general

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          DIRECCIÓN (EXECUTIVE SUITE)                        │
│   Agente Jefe de Gabinete · Dashboard CEO · Directrices · Presupuestos      │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │ directrices / presupuestos / vetos del CEO
┌───────────────┼──────────────────────────────── Event Bus (NATS/JetStream) ─┐
│               ▼                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  RESEARCH    │  │  BACKTEST    │  │  VALIDATION  │  │ MACRO & NEWS │     │
│  │  LAB         │→ │  DEPT        │→ │  DEPT        │  │  DEPT        │     │
│  │ 3-5 agentes  │  │ 2-3 agentes  │  │ 2 agentes    │  │ 2 agentes    │     │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
│         │                 │                 │                 │             │
│         └────────┬────────┴────────┬────────┘                 │             │
│                  ▼                 ▼                          ▼             │
│           ┌───────────────────────────────────────────────────────┐        │
│           │        RISK DEPT  (Comité de Riesgos, 2 agentes)      │        │
│           │   pre-trade gate · límites de portfolio · veto        │        │
│           └───────────────────────┬───────────────────────────┘        │
│                                   │ órdenes autorizadas                │
│           ┌───────────────────────▼───────────────────────────┐        │
│           │        EXECUTION & OPS DEPT (2-3 agentes)         │        │
│           │   enrutamiento · broker adapters · monitorización │        │
│           └───────────────────────────────────────────────────┘        │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ PLATAFORMA (infraestructura compartida, no es un departamento)   │   │
│  │  · Memoria colectiva: Postgres + TimescaleDB + object store      │   │
│  │  · Audit log inmutable (append-only)                             │   │
│  │  · Feature store y caché de datos de mercado                     │   │
│  │  · Orchestrator (colas de trabajo, presupuesto de cómputo)        │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

**Clave conceptual:** los departamentos son *dominios lógicos* sobre un bus de eventos.
Cada departamento tiene uno o más agentes (procesos independientes, aislados, con su
propio presupuesto de tokens/cómputo). Ningún agente llama directamente a otro: toda
comunicación es por mensajes publicados en el bus, lo que da desacoplamiento, trazabilidad
y la posibilidad de reproducir cualquier decisión con el log de eventos.

---

## 3. Departamentos y agentes

### 3.1 Research Lab (Laboratorio de Estrategias)

**Misión:** generar continuamente hipótesis de trading algorítmico nuevas y mejores.

| Agente | Rol | Perfil |
|--------|-----|--------|
| `research-hypothesis` (×2) | Genera hipótesis: patrones, señales, factores, regímenes | LLM con herramientas de análisis de datos (puede ejecutar Python sobre datos históricos en sandbox) |
| `research-coder` (×2) | Convierte una hipótesis en una especificación de estrategia ejecutable (JSON + código candidato) | LLM especializado en código |
| `research-curator` (×1) | Prioriza la cola de hipótesis según la memoria colectiva (qué ya falló, qué funciona ahora), deduplica y asigna presupuesto de investigación | LLM + reglas |

**Entradas:** directivas del CEO (clases de activo, horizontes, restricciones), alertas de
Macro & News, hallazgos de la memoria colectiva, resultados de post-mortems.
**Salidas:** `strategy.proposal.v1` → cola de Backtest.

**Regla anti-alucinación:** toda hipótesis debe incluir (a) la hipótesis económica en una
frase, (b) activos y timeframe, (c) señales de entrada/salida formales, (d) el riesgo
estimado a priori. La especificación se valida con un esquema JSON estricto antes de
aceptarla; los rechazos de esquema se registran como aprendizaje.

### 3.2 Backtest Department

**Misión:** evaluar objetivamente las propuestas con datos históricos.

| Agente | Rol | Perfil |
|--------|-----|--------|
| `backtest-engineer` (×2) | Ejecuta backtests con la API determinista del motor (vectorizado + evento a evento), con costes, slippage y tasas realistas | Código determinista orquestado por LLM |
| `backtest-analyst` (×1) | Interpreta resultados, detecta sobreajuste grosero (número de parámetros vs. muestras, sensibilidad a hiperparámetros) y redacta el informe | LLM + métricas calculadas |

**Estándares duros:** datos con supervivencia de activos (sin survivorship bias), spreads y
comisiones conservadores, sin look-ahead, división train/validation/test ciega.
**Salidas:** `backtest.report.v1` con métricas (CAGR, Sharpe, Sortino, max drawdown,
profit factor, exposición, número de operaciones) y un veredicto
`PROMOVER_A_VALIDACION | RECHAZAR | REFINAR` → cola de Validation.

### 3.3 Validation Department

**Misión:** pasar las estrategias supervivientes por baterías avanzadas de estrés.

| Agente | Rol |
|--------|-----|
| `validation-quant` (×1) | Diseña y ejecuta la batería de pruebas: Monte Carlo, walk-forward, stress de régimen |
| `validation-skeptic` (×1) | Adversario dedicado: intenta derribar la estrategia con escenarios extremos; su informe es obligatorio |

**Batería obligatoria (puerta de validación):**

1. **Monte Carlo** — 10.000 permutaciones de reordenación de trades y bootstraps de
   bloques: distribución del drawdown y del capital final; percentil 5 debe seguir siendo
   rentable.
2. **Walk-forward** — ventanas deslizantes (optimizar → validar fuera de muestra); el
   degradation ratio entre in-sample y out-of-sample debe superar el umbral fijado por el CEO.
3. **Stress de régimen** — evaluación forzada en regímenes etiquetados por Macro & News
   (crisis 2008, COVID, subidas de tipos 2022, etc.).
4. **Sensibilidad de parámetros** — la meseta de rentabilidad debe ser ancha: ±20 % en cada
   parámetro no debe invertir el signo del retorno.
5. **Robustez de costes** — duplicar el slippage supuesto y comprobar que la estrategia
   sigue siendo viable.
6. **Correlación con el portfolio** — el增量 de riesgo correlacionado con estrategias ya
   vivas debe ser aceptable (datos del Risk Dept).

**Salida:** `validation.verdict.v1` = `VALIDADA | RECHAZADA` con informe completo → cola de
Risk (para aprobar despliegue) o de vuelta a Research (con el porqué del rechazo).

### 3.4 Risk Department (Comité de Riesgos)

**Misión:** última barrera antes de operar. Analiza y valida **toda** operación y todo
despliegue. Si algo no cumple, no es válido — sin excepciones.

| Agente | Rol |
|--------|-----|
| `risk-pretrade` (×1, determinista + LLM para explicación) | Gate pre-trade en línea: valida cada orden contra límites |
| `risk-portfolio` (×1) | Vigila el riesgo agregado: exposición por activo/sector/divisa, drawdown del portfolio, correlaciones en vivo, VaR/ES |

**Límites duros (configurables solo por el CEO, con doble confirmación):**

- Riesgo máximo por operación: % fijo del capital (p. ej. 0,5–1 %).
- Exposición máxima por activo, sector y divisa.
- Drawdown máximo diario / semanal / total del portfolio → reducción automática de
  tamaño y, al superarse, modo de solo-cierre.
- Número máximo de posiciones correlacionadas.
- Apalancamiento máximo global.
- Lista de vetos absolutos: sin operación fuera del universo autorizado, sin órdenes sin
  stop, sin estrategias sin contrato de riesgo firmado.

**Respuesta en línea:** el gate pre-trade es un servicio de baja latencia (< 50 ms p99)
que responde `AUTORIZADA (con tamaño máximo) | REDUCIR | RECHAZADA (motivo)` a cada
`order.request.v1`. Cada rechazo genera evento y registro de auditoría; los rechazos
alimentan la memoria (los patrones de rechazo enseñan a Research qué proponer).

### 3.5 Execution & Ops Department

*Departamento necesario para que el sistema opere de verdad; el diseño lo añade explícitamente.*

**Misión:** ejecutar las órdenes autorizadas y operar la infraestructura.

| Agente | Rol |
|--------|-----|
| `execution-router` (×1) | Convierte órdenes autorizadas en órdenes de broker (algoritmos: marketable limit, TWAP simple, splitting), gestiona reintentos y estados parciales |
| `ops-monitor` (×1) | Salud del sistema, latencias, fallos de datos, discrepancias de posiciones (reconciliación con el broker cada N minutos) |
| `ops-bookkeeper` (×1) | Registro contable de fills, P&L realizado/no realizado, alimentación del audit log |

### 3.6 Macro & News Department

**Misión:** contexto de mercado, regímenes y gestión de eventos.

| Agente | Rol |
|--------|-----|
| `macro-analyst` (×1) | Clasifica el régimen de mercado (tendencia/rango, riesgo on/off, ciclo de tipos) a partir de datos macro y de mercado; publica `macro.regime.v1` que consumen Research y Risk |
| `news-analyst` (×2) | Ingesta y análisis de noticias/calendario económico; publica alertas (`news.alert.v1`) con categoría, relevancia y horizonte; puede pedir "modo defensa" a Risk ante eventos de cola (p. ej. NFP, decisiones de bancos centrales) |

**Contrato con el resto:** este departamento no prohíbe operaciones; publica información
que Risk convierte en restricciones (p. ej. "sin aperturas nuevas 30 min antes de X").

### 3.7 Dirección (Executive Suite)

**Misión:** interfaz de gobierno del CEO y coordinación de alto nivel.

| Agente | Rol |
|--------|-----|
| `chief-of-staff` (×1) | Sintetiza el estado de todos los departamentos, prepara el informe diario para el CEO, escruta las solicitudes de los departamentos (presupuestos, cambios de límites) y ejecuta las directrices del CEO |
| Dashboard CEO | UI web: P&L, exposición, estrategias vivas, pipeline de investigación, alertas, y consola de directrices |

**Poderes del CEO (vía dashboard o consola, con doble confirmación):**

- Aprobar/rechazar el despliegue inicial de una estrategia validada.
- Modificar límites de riesgo y presupuestos (cómputo, capital por estrategia).
- Pausar/retirar cualquier estrategia o departamento.
- Poner el sistema en `PAPER`, `LIVE_CAPITAL_REDUCIDO` o `LIVE`.
- Dar directrices estratégicas que `chief-of-staff` traduce en tareas para los departamentos.

---

## 4. Comunicación entre departamentos

### 4.1 Transporte

- **Event Bus** con persistencia y replay: **NATS JetStream** (o Redpanda/Kafka).
- Todos los mensajes son eventos versionados con sob (`{type}.v{n}`), remitente, id de
  correlación e id de causa (encadena decisiones).
- Cada departamento tiene su cola; los agentes dentro de un departamento compiten por los
  mensajes de su dominio (work queue) y publican en temas compartidos.
- Contratos de mensajes definidos como **schemas versionados** (JSON Schema / Protobuf) en
  `contracts/`; un mensaje que no cumple el esquema se rechaza en el borde del bus.

### 4.2 Flujo canónico del ciclo de vida de una estrategia

```
Research            Backtest            Validation          Risk            CEO
   │                   │                    │                │               │
   ├ strategy.proposal ├                    │                │               │
   │──────────────────►│ backtest.report    │                │               │
   │                   ├───────────────────►│ validation.verdict ────────────┐  │
   │◄─ feedback loop (rechazos y aprendizajes) │             │               │  │
   │                                        │               ├─ deploy.request│  │
   │                                        │               │  (espera firma)│  │
   │                                        │               │◄── CEO aprueba ┘  │
   │                                        │               │ strategy.deployed │
```

A partir de `strategy.deployed`, la estrategia entra en el **portfolio** y su ciclo diario es:

```
datos de mercado ──► señales de estrategias ──► order.request.v1
                                                        │
                        Risk pre-trade gate ◄───────────┘
                                │ AUTORIZADA
                                ▼
                      Execution Dept → broker → fills → contabilidad → memoria
```

### 4.3 Tipos de interacción

1. **Evento (fire-and-forget):** datos, regímenes, alertas.
2. **Petición-respuesta (request/reply):** gate de riesgo, presupuesto de cómputo.
3. **Cola de trabajo:** propuestas de estrategias, baterías de validación.
4. **Blackboard (memoria compartida estructurada):** estado actual del portfolio,
   veredictos, aprendizajes; los agentes leen/escriben con control de concurrencia.

---

## 5. Memoria colectiva y persistencia

Todo el estado vive fuera de los agentes (P4). Cuatro capas:

| Capa | Tecnología | Contenido |
|------|-----------|-----------|
| **Memoria operacional** | Postgres | Estado actual: posiciones, órdenes, estrategias vivas, límites vigentes, colas |
| **Memoria de series** | TimescaleDB (extensión de Postgres) | Datos de mercado, features calculadas, métricas de rendimiento, regímenes, señales emitidas |
| **Memoria episódica y semántica** | Postgres + object store + índice vectorial (pgvector) | Informes de backtest, baterías de validación, post-mortems, "lecciones aprendidas" estructuradas, hipótesis y su desenlace. Búsqueda semántica para que Research consulte "qué se intentó y por qué falló" |
| **Audit log** | Append-only (tabla inmutable + hash encadenado, exportación a object store con retención larga) | Cada mensaje del bus relevante, cada decisión con sus entradas, cada cambio de configuración con autor. Es la fuente para reproducir y auditar |

**Esquemas clave (resumen):**

- `strategies(id, spec_json, version, status, owner_agent, created_at)` —
  status: `PROPUESTA → EN_BACKTEST → VALIDADA → APROBADA → PAPEL → VIVA → RETIRADA/BLOQUEADA`
- `evaluations(strategy_id, kind, result_json, verdict, report_uri, created_at)`
- `lessons(content, tags, source_evaluation_id, embedding, times_referenced)` — la memoria
  de aprendizaje que `research-curator` consulta antes de proponer
- `orders`, `fills`, `positions`, `risk_checks(order_id, verdict, reason)`
- `directives(ceo_id, text, scope, status, effective_at)` — directrices vigentes e históricas
- `audit_log(seq, ts, actor, event_type, payload, prev_hash, hash)`

**Aprendizaje continuo en la práctica:**

1. Cada evaluación (backtest/validación/rechazo de riesgo) genera 0–n `lessons`
   estructuradas ("estrategias de reversión en cripto 1m sobreajustan con < 200 trades").
2. El `research-curator` inyecta las lecciones más relevantes en el prompt de generación.
3. Revisión semanal automática: los post-mortems de estrategias retiradas y semanas con
   pérdidas generan lecciones nuevas; el CEO ve un resumen.
4. El rendimiento real vs. previsto de cada estrategia viva se compara cada semana
   (drift detection); la desviación dispara re-validación o retiro.

---

## 6. Gestión del portfolio

- **Contrato de riesgo por estrategia:** al aprobarse, cada estrategia firma un contrato
  (riesgo por operación, drawdown máximo propio, universo, tamaño máximo, restricciones de
  horario). El gate de riesgo lo aplica automáticamente.
- **Asignación de capital:** pesos basados en volatilidad objetivo (risk parity simple como
  punto de partida) con techo por estrategia; el CEO fija el capital total y el % en papel.
- **Comité semanal automático:** Risk + Validation re-puntúan el portfolio (rendimiento,
  correlaciones, regímenes) y proponen: subir capital, mantener, reducir o retirar.
  Las decisiones por debajo de umbrales son automáticas; el resto llega al CEO.
- **Modos de defensa** (activados por Risk, con aviso al CEO): reducir exposición nueva,
  apretar stops, o pasar a solo-cierre ante regímenes de crisis detectados por Macro.

---

## 7. Stack tecnológico propuesto

| Componente | Elección | Motivo |
|-----------|----------|--------|
| Lenguaje núcleo | **Python 3.12** + Pydantic | Ecosistema cuant/financiero, schemas estrictos |
| Agentes LLM | SDK de agentes (p. ej. Amp plugin / framework propio ligero) con herramientas restringidas por rol | Cada agente solo ve las herramientas de su departamento |
| Modelos LLM | Intercambiables por agente a través del **Model Gateway** (§7.1): ningún agente conoce el proveedor | Permite modelos rápidos/baratos en roles decisionales y modelos potentes en roles técnicos, sin tocar código |
| Motor de backtest | Vectorizado propio sobre NumPy/Pandas + simulador de eventos para validación final | Control total de costes/look-ahead; sin cajas negras |
| Event bus | NATS JetStream | Persistencia, replay, request/reply, ligero |
| Almacenes | Postgres + TimescaleDB + pgvector; object store (S3/MinIO) para informes | Una pieza de datos menos que mantener; SQL para auditoría |
| Ejecución | Adaptadores por broker/exchange detrás de una interfaz `BrokerAdapter`; primero paper, luego real | Intercambiable y testeable |
| Orquestación | Contenedores (Docker Compose → K8s si hace falta); agentes como workers sin estado | Reemplazabilidad (P5) |
| Dashboard CEO | Web (React/Next) + API propia | Gobierno y observabilidad |
| Secretos | Gestor de secretos; las claves de broker nunca en el repo ni en prompts | Seguridad |

---

### 7.1 Capa de modelos intercambiables (Model Gateway)

Los modelos de los agentes son **configuración, no código**. Ningún agente conoce qué
proveedor o modelo usa: todos llaman a un único punto de entrada (Model Gateway) con una
interfaz común (chat + herramientas + salida con esquema JSON).

**Configuración por agente** (en `config/models.yaml`, versionada en el repo):

```yaml
models:
  jev:                       # modelo de DECISIÓN (evaluación), no de chat
    id: typesafe-ai/jev      # vía Vercel AI Gateway
    kind: evaluator          # devuelve booleanos con probabilidad, scores y opciones
    input_cost_per_mtok: 0.042
    context_window: 32000
  frontier-strong:
    kind: generative
    tier: premium
  frontier-lite:
    kind: generative
    tier: standard

agents:
  macro-analyst:
    generative: frontier-lite          # redacta los informes de régimen
    decisions: jev                     # clasifica régimen, relevancia y horizonte
  news-analyst:
    generative: frontier-lite
    decisions: jev                     # triaje de noticias (relevante / acción / ruido)
  research-hypothesis:
    generative: frontier-strong        # crea hipótesis y código
    decisions: jev                     # deduplica y puntúa contra la memoria
  risk-portfolio:
    generative: frontier-lite          # explica en lenguaje natural
    decisions: jev                     # pre-puntúa rubrics de riesgo (nunca autoriza)
  chief-of-staff:
    generative: frontier-strong
    decisions: jev                     # prioriza solicitudes y alertas
```

**Patrón generativo + evaluador:** los agentes *decisionales* no necesitan un modelo
grande para decidir, necesitan uno barato que puntúe. El patrón es: el modelo generativo
(ligero) produce el contenido o el análisis, y **Jev arbitra** las decisiones
estructuradas sobre ese contenido: `es_relevante`, `prioridad`, `regimen`,
`probabilidad_impacto`, `rubric_de_riesgo`. Como Jev evalúa varias preguntas en paralelo
en una sola petición y cuesta ~$0.042/M tokens de entrada, las decisiones de alto volumen
(triaje de noticias, priorización de hipótesis, puntuación de rubrics) son prácticamente
gratuitas.

**Dónde aplica Jev por departamento:**

| Departamento | Decisiones delegadas a Jev |
|---|---|
| Macro & News | Clasificación de régimen, triaje de noticias, detección de eventos de cola |
| Research Lab | Deduplicación de hipótesis, puntuación de novedad y ajuste a lecciones aprendidas |
| Validation Dept | Puntuación de rubrics de los informes, detección de debilidades del *skeptic* |
| Risk Dept | Pre-puntuación de rubrics y flags; **la autorización final siempre es determinista** |
| Dirección | Priorización de solicitudes de departamentos, resúmenes de escrutinio |

**Límites de Jev que el diseño respeta:** contexto de 32k tokens (no lee documentos
largos: recibe el estado estructurado y las preguntas, no el informe completo) y **no
genera texto** (máximo de salida 0): todo lo que un agente debe *escribir* sale del
modelo generativo de su rol. Por eso el Gateway tipa los modelos (`evaluator` vs
`generative`) y rechaza en configuración una asignación inválida, p. ej. un agente sin
generativo que deba redactar informes.

**Políticas de enrutado del Gateway:**

1. **Por rol:** las decisiones estructuradas de los departamentos decisionales van a Jev
   (rápido, ~gratuito); los modelos generativos se dimensionan por rol (§3). Las tareas
   técnicas (generación de hipótesis, código de estrategia, informes de validación) usan
   modelos generativos de mayor capacidad.
2. **Por complejidad de tarea:** el Gateway puede degradar a un generativo ligero las
   tareas rutinarias y escalar las difíciles; las decisiones tipadas siempre van a Jev
   salvo que la pregunta exceda su contexto (entonces, resumir primero con el generativo
   ligero).
3. **Por presupuesto:** cada agente tiene presupuesto de tokens/coste; al agotarse, el
   Gateway degrada automáticamente al modelo económico o devuelve `PRESUPUESTO_AGOTADO`
   y la tarea se reencola — nunca se salta un gate por ahorro.
4. **Fallback y salud:** timeouts, reintentos y caída a un modelo alternativo ante caídas
   del proveedor, con evento `model.failover.v1` en el audit log. Si Jev cae, las
   decisiones estructuradas se resuelven con reglas deterministas de respaldo definidas
   por rol — un corte del modelo de decisión nunca paraliza un departamento.

**Registro de calidad por modelo:** cada respuesta relevante queda asociada a
`(agente, modelo, tarea, resultado)`; el pipeline produce métricas de calidad por modelo
y rol (tasa de esquemas válidos, tasa de promoción de hipótesis generadas, coste por
hipótesis promovida). Esto permite al CEO cambiar asignaciones de modelo con datos, vía
dashboard, sin desplegar código.

**Regla de seguridad:** el modelo es intercambiable; las herramientas y permisos de cada
agente **no** dependen del modelo y siguen definidas por rol (§8). Cambiar de modelo nunca
amplía los permisos de un agente.

---

## 8. Seguridad y control de acceso

- Cada agente tiene **credenciales de mínimo privilegio**: `research-coder` ejecuta código
  en sandbox sin red y sin credenciales de broker; ningún agente LLM tiene credenciales de
  broker — solo `execution-router` (determinista) las usa.
- Presupuestos por agente (tokens/hora, cómputo/hora) con corte automático.
- Cambios de límites de riesgo requieren doble confirmación del CEO en el dashboard.
- Procedimiento de **kill switch**: botón global y por departamento; apaga la toma de
  nuevas posiciones y opcionalmente cierra todas.

---

## 9. Puntos de decisión humana (gobierno)

| Decisión | Quién | Frecuencia |
|----------|-------|-----------|
| Despliegue inicial de estrategia en papel o capital real | CEO | Por estrategia |
| Cambio de límites de riesgo o presupuestos | CEO (doble confirmación) | Por cambio |
| Modo del sistema (PAPER / REDUCIDO / LIVE) | CEO | Por cambio |
| Todo lo demás (proponer, backtestear, validar, rechazar, ejecutar) | Automático | Continuo |
| Informe diario y semanal con propuestas del comité | CEO decide | Diario/semanal |

---

## 10. Hoja de ruta por fases

**Fase 0 — Cimientos (2–3 semanas)**
Repositorio, contratos de mensajes, Postgres/Timescale, bus de eventos, esqueleto de
agentes con heartbeat, audit log, dashboard mínimo. Sin LLM todavía.

**Fase 1 — Pipeline de investigación (3–4 semanas)**
Research → Backtest → Validation end-to-end con datos históricos reales y la batería
Monte Carlo/walk-forward. Salida: catálogo de estrategias validadas en papel.

**Fase 2 — Riesgo y ejecución en papel (3 semanas)**
Gate pre-trade, contratos de riesgo, execution router con broker paper, monitorización y
reconciliación. El sistema opera solo en papel y publica el informe diario.

**Fase 3 — Memoria y evolución (2–3 semanas)**
Lecciones aprendidas, post-mortems automáticos, curator con memoria, revisión semanal del
portfolio, drift detection.

**Fase 4 — Capital real gradual (según resultados en papel ≥ 4–8 semanas)**
Modo `LIVE_CAPITAL_REDUCIDO`, con límites conservadores; escalado progresivo supervisado
por el CEO.

---

## 11. Métricas del sistema (KPIs)

- **Negocio:** P&L ajustado a riesgo (Sharpe del portfolio), drawdown máximo, % del
  capital expuesto, beneficio por estrategia.
- **Pipeline:** hipótesis/semana, tasa de promoción backtest→validación, tasa de
  validación→producción, tiempo medio de idea→papel.
- **Calidad:** desviación rendimiento real vs. previsto, nº de vetos de riesgo/mes y su
  acierto, incidentes de datos, reconciliaciones fallidas.
- **Aprendizaje:** lecciones generadas/referenciadas; mejora de la tasa de promoción en el
  tiempo (proxy de que el sistema "aprende").

---

## 12. Riesgos del proyecto y mitigaciones

| Riesgo | Mitigación |
|--------|-----------|
| Sobreajuste masivo del pipeline de investigación | Batería de validación adversaria (validation-skeptic), walk-forward obligatorio, penalización por nº de parámetros |
| Alucinaciones de LLM en decisiones críticas | P1: LLM solo propone; gates deterministas disponen; esquemas estrictos en todos los mensajes |
| Fuga de capital por bug de ejecución | Capital reducido, límites duros, reconciliación continua, kill switch, prueba de caos semanal |
| Degradación silenciosa de estrategias vivas | Drift detection semanal, re-validación obligatoria, retiro automático por drawdown propio |
| Coste descontrolado de LLM/cómputo | Presupuestos por agente con corte, priorización por curator |
| Pérdida de auditoría | Log inmutable con hash encadenado + exportación periódica fuera del clúster |
