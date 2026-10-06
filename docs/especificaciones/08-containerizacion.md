# Especificación: Fase 8 — Containerización por departamento

*Guardarraíles transversales: ver [00-marco-guardarrailes.md](00-marco-guardarrailes.md).
Depende de: capacidades de Fases 0–7. Es base técnica previa a cualquier evaluación de capital real.*

## 1. Misión y alcance

Convertir el sistema en un conjunto de **procesos residentes por departamento** que se
comunican exclusivamente por NATS JetStream, desplegados con docker-compose. Hoy el ciclo
diario es monolítico: `tf/scheduler.py` crea un `AgentHost` en memoria por ciclo y
`tf/paper.py` monta un `InMemoryBus` por sesión. El bus NATS existe (`tf/bus_nats.py`) y
está testeado, pero no es aún la columna vertebral. Esta fase mueve el acoplamiento del
proceso al bus, sin cambiar la lógica de negocio.

**No es alcance:** orquestadores tipo K8s, brokers reales, autenticación del dashboard
(se especifica aparte como prerrequisito de modo live).

### Estado de implementación (2026-10)

- Existe `DepartmentRunner` y `python -m tf.runner` con consumers durables, ack/nak
  explícito, extensión de ack para trabajos largos, reintentos, DLQ e inbox persistente por
  departamento/envelope. `tf-research`, `tf-backtest`, `tf-validation`, `tf-macro-news` y
  `tf-executive` ya tienen factories y servicios Compose independientes; Risk/Execution aún no.
- El perfil `pipeline` coordina un ciclo Research→Backtest→Validation + Macro/News + informe
  ejecutivo con snapshots de mercado SHA-256, referencias autocontenidas en los mensajes,
  IDs estables y probes de readiness. `tf-ingest` prepara el dataset y `tf-scheduler` lanza
  el pipeline a la hora UTC configurada; `tf-cycle` sigue siendo el flujo end-to-end
  monolítico de transición. El pipeline separado aún no incluye paper.
- El append de audit PostgreSQL serializa escritores con advisory lock. `tf_state`
  comparte budget G3, memoria y estado del ciclo; los JSON heredados se importan una sola
  vez y `DailyCycle` toma un lock global. La memoria se escribe atómicamente como documento
  JSON (sin esquema normalizado por lección/evaluación).
- Budget reserva llamadas por agente antes de invocar proveedor, pero todavía no reserva
  coste/tokens estimados de llamadas concurrentes; no escalar los consumidores LLM hasta
  cerrar ese límite o centralizar las llamadas en el gateway.
- **No habilitar réplicas LLM ni capital real:** JetStream entrega al menos una vez. El inbox
  persistente y los IDs estables protegen los workers batch; falta una outbox transaccional
  para cerrar la ventana entre publicación y commit. Risk/Execution conservan contexto paper
  en memoria. Budget reserva llamadas atómicamente, pero falta reservar coste/tokens antes
  de llamadas LLM concurrentes.

## 2. Decisión de topología: un contenedor por departamento, no por agente

| Criterio | Razón |
|---|---|
| Frontera de despliegue = frontera de confianza | Los permisos/ACL ya están modelados por departamento (G1, Permission Broker); el dominio de riesgo de un agente coincide con su departamento |
| Latencia del camino crítico | `order.request → risk.decision → fill` ocurre intra-proceso hoy; partir un departamento por agente multiplica saltos de red en el gate (SLA p99 < 50 ms de 04-risk) |
| Escalado | Solo research/backtest/validation son bursty; se escalan con **queue groups** (réplicas del mismo departamento), que por-agente no aporta |
| Fail-closed | El gate de riesgo **no puede escalarse activo-activo** (veto split-brain); con contenedor por departamento el modelo es 1 activa + 1 standby |
| Operaciones | 7 servicios + 4 de plataforma es administrable; 20+ microservicios no |

## 3. Topología de despliegue (docker-compose)

| Servicio | Imagen | Réplicas | Escalado | Notas |
|---|---|---|---|---|
| `tf-research` | `tf:phase8` | 1→N | queue group `research` (JetStream workqueue) | bursty; LLM |
| `tf-backtest` | `tf:phase8` | 1→N | queue group `backtest` | bursty, CPU |
| `tf-validation` | `tf:phase8` | 1→N | queue group `validation` | Monte Carlo; puede ir en contenedor sin red (G6) |
| `tf-risk` | `tf:phase8` | **1 + standby** | nunca activo-activo | suscribe `order.request.v1`; núcleo firmado (K-1) |
| `tf-execution` | `tf:phase8` | 1 | standby; idempotencia E-2 ya cubierta | suscribe `risk.decision.v1` |
| `tf-macro-news` | `tf:phase8` | 1 | — | egress para GDELT, RSS y Finnhub; `tf-ingest` tiene egress independiente a Yahoo |
| `tf-executive` | `tf:phase8` | 1 | — | chief-of-staff, informes, tally |
| `tf-ingest` | `tf:phase8` | job | — | descarga snapshot AAPL del día; fuente Yahoo |
| `tf-pipeline` | `tf:phase8` | job | — | trigger/waiter de ciclo; recibe `validation.verdict.v1` y el informe ejecutivo |
| `tf-scheduler` | `tf:phase8` | 1 | lock Postgres | corre el pipeline diario a `TF_SCHEDULE_UTC`; mismo día no se repite tras éxito |
| `nats` | `nats:2` (JetStream) | 1 (post-fase 4: cluster 3) | — | monitor 8222 |
| `postgres` | `timescaledb` | 1 | — | audit/budget/memoria/ledger |
| `dashboard` | `tf-dashboard` | 1 | — | detrás del SSO/proxy del CEO (limitación conocida de `dashboard/README.md`) |

Una sola imagen `tf` para todos los departamentos: `docker run tf tf-run --department research`.
El departamento es configuración de arranque, no una imagen distinta (menos derivas, mismo
pipeline CI).

## 4. El runner: `tf/runner.py` (pieza nueva central)

Cada contenedor de departamento ejecuta el mismo ciclo:

1. Construir `NatsBus` (reconnect con backoff, `max_reconnect=-1`) y `AuditLog` (Postgres).
2. Instanciar los agentes del departamento tal como los registran hoy
   `tf/departments.py` / `tf/pipeline.py` (`Department()` ya devuelve el registro: nombre,
   workers, suscripciones — reutilizar sin cambios).
3. `AgentHost.register(...)` y entrar en **bucle residente**: `drain(max_steps)` en
   iteraciones con `idle_sleep` pequeño, en lugar del drain único por ciclo.
4. Heartbeat: publicar `agent.heartbeat.v1` cada 10 s (esqueleto existente en
   `tf/agents.py`); un runner sin heartbeat > 60 s se marca `ops.incident`.
5. Señales: SIGTERM ⇒ dejar de aceptar mensajes (unsubscribe), terminar el envelope en
   curso, cerrar conexión (drain limpio; nada se pierde porque el stream es durable).

El runner **no contiene lógica de negocio**: es pegamento de proceso. Los tests actuales
(siguen corriendo con `InMemoryBus`) no se tocan.

CLI: `python -m tf.runner --department <nombre> --factory paquete.modulo:factory`.
La factory recibe `(bus, audit, department)` y devuelve `(workers, msg_types)` para
registrar workers locales sin suscripciones efímeras duplicadas. Requiere
`TF_DATABASE_URL`; verifica la cadena al arrancar y no tiene fallback local.

## 5. Fiabilidad del bus (contrato JetStream)

- **Stream único `TF`** sobre `>` con `discard_new` NO: retención por límites de tiempo;
  cada departamento consume desde su propio **durable consumer** con filtro de sujetos.
- **Queue groups** (`deliver_group`) solo en research/backtest/validation; riesgo,
  ejecución y dirección usan consumer exclusivo.
- **Ack manual tras procesar**, `max_ack_pending` acotado por cola del host (techo ya
  existente: `host.queue_overflow`), `max_deliver=3` y después **DLQ** en sujeto
  `tf.dlq.<sujeto>` que el chief-of-staff refleja como `ops.incident` (nunca se descarta
  en silencio).
- **Idempotencia:** el dedup por `envelope.id` de `AgentHost` ya protege re-entregas
  (redelivery de JetStream es normal); se audita como hoy (`agent.loop_blocked`) y se
  ack-ea. Ver `contracts.py` (regla transversal 5).
- **`cycle.trigger.v1`** (nuevo contrato en `contracts.py`): lo publica el scheduler;
  macro-news lo primero, luego research, y executive cierra el ciclo con el informe.
  El payload lleva `fecha_ciclo` y `forzar_comite_semanal`.

## 6. Externalización de estado (requisito previo a réplicas)

Hoy viven en `state/` (disco local, incompatible con N contenedores):

| Estado | Destino | Pieza |
|---|---|---|
| Audit log | Postgres (existe `tf/audit_pg.py`) | verificar cadena de hash tras cada arranque (ya se hace por ciclo) |
| Presupuesto G3 | Postgres, tabla `budget_state` (upsert atómico por agente+hora+día) | los check() del governor son de lectura/escritura corta; sin caché local |
| Memoria colectiva | Postgres (tablas de `migrations/0001_init.sql` + nuevas) | `tf/memory.py` ya deduplica; cambiar sink de JSON a PG |
| Estado del ciclo (última ingesta, comité) | Postgres, clave `scheduler/state` | para que un `tf-scheduler` reiniciado no repita ciclo |
| CSVs de market data | Postgres `market_data` (vía ingesta) + volumen compartido read-only para el cache | único volumen `named volume` del compose |

Regla transversal 1 del marco se cumple así de verdad: *ningún contenedor con estado
propio*; matar y recrear cualquier departamento no pierde información de negocio.

## 7. Guardarraíles específicos de esta fase

| # | Guardarrail | Tipo |
|---|---|---|
| C-1 | **ACL NATS por departamento:** cada servicio se autentica con un usuario cuyo token solo permite publicar en sus sujetos declarados (`publish` en su salida) y leer sus suscripciones; la matriz vive en `config/acl.yaml` y se genera al build | G6: el bus también valida — un contenedor comprometido no puede fingir `risk.decision.v1` |
| C-2 | **Ningún departamento toca Postgres salvo audit/budget/memory vía su capa de plataforma** — no hay acceso SQL directo desde agentes | G4 |
| C-3 | **Risk sin red exterior:** su contenedor no tiene egress (el gate solo lee bus + config); validado en CI con prueba de connectividad | G6 |
| C-4 | **Secretos solo por env (`secrets:` de compose / `.env` fuera de git):** nunca en imágenes ni en `config/` | G6 |
| C-5 | **El runner se niega a arrancar si su registro de departamento no valida** contra `config/guardrails.yaml` (mismo fail-fast que el Model Gateway al arranque) | G1/G7 |
| C-6 | **Veto del gate intocable por el despliegue:** el pipeline de imagen no modifica `tf/risk.py`; K-1 se extiende a que ninguna réplica adicional de `tf-risk` puede arrancar si detecta otra activa (lock en Postgres `risk_gate_lock`) | K-1 |
| C-7 | **Prohibición de estado en disco local:** CI falla si un runner nuevo escribe dentro de `state/` | transversal-1 |

## 8. Modos de fallo y degradación

- **Cae un departamento worker (research/backtest/validation):** JetStream retiene; al
  volver, consume el backlog. El ciclo en curso no se detiene; los informes marcan
  `ops.incident`.
- **Cae `tf-risk`:** los mensajes `order.request.v1` se acumulan sin ack → **no hay
  ejecución nueva** (fail-closed por construcción, no por código). El standby takeover
  solo es legítimo tras liberar `risk_gate_lock` (C-6). `tf-execution` además tiene su
  auto-suspensión E-5.
- **Cae `tf-execution`:** tokens de riesgo expiran por TTL (≤ 60 s) ⇒ cualquier reintento
  exige decisión nueva; nunca se ejecuta con token caducado.
- **Cae NATS:** todo el sistema se detiene en seco (sin bus no hay decisiones); los
  runners reconectan con backoff y el ciclo ripresa solo. No existe modo "local degradado"
  en producción — el `InMemoryBus` queda solo para tests/demos.
- **Cae `tf-macro-news`:** sin régimen ni noticias el ciclo sigue con el último régimen
  persistido, penalizado en confianza (M-3 ya implementado).
- **Departamento duplicado por error de deploy:** C-6 (lock) y los consumers exclusivos
  lo impiden; los queue groups toleran duplicados por diseño (idempotencia).

## 9. Plan de ejecución (hitos, en orden)

1. **H1 · Runner + trigger por bus:** `tf/runner.py`, contrato `cycle.trigger.v1`,
    factories para el pipeline de investigación, Macro/News y Executive, además de
    `scripts/run_distributed_pipeline.py`. **Parcial:** el ciclo distribuido y el scheduler
    diario completan research→veredicto→informe por NATS; falta integrar paper/Risk/Execution.
2. **H2 · Estado a Postgres:** budget, memoria y scheduler-state (`tf_state`, migraciones
   `0002_runtime_state.sql` y `0003_runner_inbox.sql`). **Parcial:** ciclo monolítico y
   memoria de los workers usan Postgres; falta normalizar lecciones/evaluaciones y completar
   la outbox que enlaza transacciones de estado con publicaciones NATS.
3. **H3 · Dockerfile + compose fase 8:** imagen única, healthchecks (heartbeat + 8222 +
   pg_isready), acl.yaml y usuarios NATS generados al arranque. Verificación:
   `docker compose up` + ciclo completo + `pnpm typecheck` del dashboard intacto.
   **Parcial:** imágenes Python/dashboard y perfiles `app`/`pipeline` existen; `tf-cycle`
   sigue siendo transición monolítica para paper y faltan ACL/usuarios NATS por departamento.
4. **H4 · Escalado y HA:** queue durable multi-subject está implementado y Backtest/Validation
   se verifican en Compose con dos réplicas cada uno. Siguiente: medir throughput/latencia,
   probar caída de una réplica con backlog y añadir fencing/standby para Riesgo (que sigue
   single-active); Research/Macro/Executive siguen en una réplica.
5. **H5 · Prueba de caos semanal** (riesgo §12 de la arquitectura): script
   `scripts/run_chaos.py` que mata contenedores en medio de un ciclo paper y verifica
   invariantes: ningún fill sin `risk_token` válido, ningún duplicado por redelivery,
   cadena de hash íntegra. Corre en CI del orb contra bus en memoria (simulación) y en
   máquina local contra compose (`-m infra`).
6. **H6 · Antes de Fase 4:** autenticación del dashboard + SSO/proxy; export periódico del
   audit fuera del clúster (riesgo "pérdida de auditoría").

## 10. KPIs de la fase

Latencia end-to-end del ciclo (trigger→informe) sin degradar vs monolito · p99 del
gate intra e inter-contenedor (objetivo: sin cambio material) · backlog máximo procesado
tras caída de un departamento · % de ciclos completados sin intervención con un contenedor
asesor matado a mitad (caos) · 0 violaciones C-1..C-7 en suite de permisos.
