# Fase 3 — Memoria y evolución (implementada)

Lecciones aprendidas automáticas, memoria consultable por Research, drift detection y
comité semanal. Según [docs/arquitectura.md §5-6](arquitectura.md) y la hoja de ruta.

## Qué hay

| Pieza | Módulo | Reglas que implementa |
|---|---|---|
| Embeddings deterministas + similitud coseno | `src/tf/memory.py` | Mismo contrato que pgvector en producción; sin dependencia externa |
| `MemoryStore` (lecciones + evaluaciones) | `src/tf/memory.py` | Deduplicación semántica (sim ≥ 0.9 refuerza, no duplica) |
| Huella de spec (`spec_fingerprint`) | `src/tf/memory.py` | R-4: un spec exacto ya rechazado no se vuelve a proponer |
| Bloqueo de familias | `src/tf/memory.py` | R-5: 3 fracasos de la familia ⇒ bloqueada hasta directriz del CEO |
| `LessonExtractor` | `src/tf/memory.py` | Desenlaces → lecciones estructuradas (reglas en Fase 3; LLM después) |
| `DriftDetector` | `src/tf/drift.py` | Semáforo: OK / REVISAR / REVALIDAR / RETIRAR; mínimo estadístico antes de opinar |
| `WeeklyCommittee` | `src/tf/drift.py` | RETIRAR automático por contrato; REVISAR (reducir) escala al CEO |
| Post-mortems | `src/tf/drift.py` | Toda retirada genera lecciones: "backtest sobreestimaba" vs "retiro por contrato" |
| Integración pipeline ↔ memoria | `src/tf/pipeline.py` | Cada evaluación registra y extrae lecciones; Research consulta antes de proponer |
| Demo de evolución | `scripts/run_evolution.py` | 9 semanas: validación → operación → drift → retiro → post-mortem → nueva ronda |

## El bucle de aprendizaje (demostrado en el demo)

```
investigación ──► validación ──► operación semanal ──► drift detection
      ▲                                                      │
      │                            ┌──── REVISAR/REVALIDAR ──┤
      │                            └──── RETIRAR (contrato) ─► post-mortem
      │                                                          │
      └───────── memoria: no repetir ideas muertas ◄── lecciones
```

Salida del demo (`uv run python scripts/run_evolution.py`):

- Semana 0: 5 hipótesis → 1 validada, 4 lecciones ya en memoria.
- Semanas 1-4: Sharpe real 1.7-6.7 vs previsto → MANTENER.
- Semana 5: régimen cambia, Sharpe -11.17 y DD propio 14.3 % → **RETIRADA automática**
  por contrato + post-mortem archivado ("el backtest sobreestimaba el rendimiento").
- Semana 9: nueva ronda de investigación → **4 propuestas saltadas por memoria**
  (no repetir fracasos), auditadas como `research.proposal_skipped`.

## Decisiones de diseño

1. **Sin mínimo estadístico no se opina**: el drift detector devuelve OK con motivo
   "observación insuficiente" en vez de alarmar con 3 días de datos (espíritu B-4).
2. **La memoria filtra en tres niveles**: spec exacto muerto (R-4), familia bloqueada por
   3+ fracasos (R-5) y similitud semántica con lecciones de la familia.
3. **Las propuestas saltadas quedan auditadas**: el "no" de la memoria es una decisión
   trazable, no un silencio.
4. **El post-mortem distingue causas**: rendimiento peor de lo previsto (problema del
   backtest/costes) vs retiro por contrato con rendimiento coherente (pura gestión de
   riesgo). Lecciones distintas, aprendizaje distinto.

## Tests

94 en total (`uv run pytest -q`), incluidos: determinismo y semántica de embeddings,
dedup de lecciones, huella de spec y bloqueo de familias, extractor por modo de fallo,
semáforo de drift completo (incluido el orden correcto: contrato antes que Sharpe),
propuestas del comité y sus escalados al CEO, y el test de integración en el que la
memoria hace que Research salte las ideas ya fracasadas.

## Siguientes pasos (Fase 4)

Capital real gradual: adaptadores de broker reales tras la interfaz de `PaperBroker`,
modo `LIVE_CAPITAL_REDUCIDO` con límites conservadores, y panel CEO para el escalado.
Requiere infra (Postgres/NATS) fuera del orb y credenciales de broker.
