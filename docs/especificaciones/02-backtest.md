# Especificación: Backtest Department

*Guardarraíles transversales: ver [00-marco-guardarrailes.md](00-marco-guardarrailes.md).*

## 1. Misión y alcance

Evaluar objetivamente las especificaciones que llegan de Research con datos históricos y
costes realistas, y emitir un veredicto fundado: `PROMOVER_A_VALIDACION | REFINAR |
RECHAZAR`. No modifica estrategias: si una propuesta necesita cambios, la devuelve con un
informe de refinamiento.

## 2. Agentes

### 2.1 `backtest-engineer` (×2)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Configurar y ejecutar corridas del motor determinista sobre la cola de propuestas |
| Modelo | Generativo `frontier-lite` (orquesta; el cálculo es 100 % código) |
| Herramientas (G1) | `run_backtest` (trabajo en cola del motor), `read_dataset_metadata`, `read_spec`, `publish_report` |
| Publica | `backtest.report.v1`, `backtest.variant_log.v1` |

Ejecución estándar obligatoria: simulación de eventos para el veredicto final,
vectorizada para exploración; costes = comisiones reales + spread conservador (p95
histórico) + slippage de impacto para el volumen supuesto; supervivencia de activos;
división train/validation/test ciega pre-registrada.

### 2.2 `backtest-analyst` (×1)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Interpretar resultados, detectar sobreajuste grosero (nº de parámetros vs. muestras, sensibilidad), redactar el informe y emitir veredicto |
| Modelo | Generativo `frontier-lite` + `decisions: jev` (puntuación de rubric de calidad de evidencia) |
| Herramientas (G1) | `read_backtest_results`, `read_variant_log`, `publish_verdict` |
| Publica | `backtest.report.v1` con veredicto |

## 3. Guardarraíles específicos

| # | Guardarrail | Tipo |
|---|---|---|
| B-1 | **Motor versionado e inmutable:** corre con una versión fijada por la plataforma; ningún agente puede modificar el motor, los datos ni los costes por corrida | G1/G6 |
| B-2 | **Ciego al test:** el conjunto de test ciego solo es accesible al motor para la corrida final de una propuesta ya congelada; los resultados de test no son visibles durante la exploración | G4/G5 |
| B-3 | **Anti data-mining:** máx. 50 variantes de hiperparámetros por propuesta; el log de variantes es completo e inmutable (probar y "olvidar" variantes no es posible; el analyst debe reportarlas todas). Superada la cuota ⇒ `RECHAZAR` por agotamiento de evidencia | G5 |
| B-4 | **Mínimo estadístico:** propuestas con < 100 operaciones o < 2 regímenes en train no pueden promocionarse, sin excepciones | G5 |
| B-5 | **Costes conservadores no negociables:** si el spec no define costes, se aplican los del perfil conservador; "costes optimistas" son una violación V3 | G5 |
| B-6 | **Solo lectura de datos:** los datasets son de solo lectura para este departamento; no hay escritura de datos de mercado | G4 |
| B-7 | **Veredicto con rubric:** el veredicto debe mapear a la rubric de evidencia (muestreada por Jev de las métricas estructuradas); una discrepancia grave entre rubric y veredicto lo invalida | G5 |
| B-8 | Presupuesto: cola de cómputo con prioridad asignada por el curator; los backtests no interrumpen nunca el ciclo de producción de señales | G3 |

## 4. Modos de fallo y degradación

- **Motor saturado:** la cola prioriza por presupuesto/prioridad del curator; ninguna
  corrida se ejecuta con datos incompletos (fail-closed).
- **Datos corruptos o huecos:** la propuesta vuelve a la cola con `DATA_QUALITY_FLAG`;
  el informe registra el defecto de datos, no se atribuye a la estrategia.
- **Analista caído:** los ingenieros publican resultados sin veredicto; el veredicto no
  puede ser emitido por otro rol (separación de ejecución y juicio).

## 5. KPIs del departamento

Backtests/semana · coste de cómputo por propuesta · tasa de promoción a Validation ·
tasa de reintento por datos · % de veredictos confirmados después por Validation
(calibración del departmento: se mide y se publica internamente).
