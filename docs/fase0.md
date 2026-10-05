# Fase 0 — Cimientos (implementada)

Cimientos de la plataforma: contratos, bus, permisos, gateway de modelos, esqueleto de
agentes, audit log y esquema de base de datos. **Sin LLM todavía** (se enchufan en Fase 1).

## Qué hay

| Pieza | Módulo | Guardarraíl que implementa |
|---|---|---|
| Contratos de mensajes versionados (16 tipos v1) | `src/tf/contracts.py` | G2 — salida inválida nunca se publica |
| Sobré `Envelope` con actor completo (agente, rol, modelo) | `src/tf/contracts.py` | Regla transversal #6 |
| Bus de eventos con validación en el borde | `src/tf/bus.py` | G2 |
| Permission Broker con escalado V3 (3 violaciones = suspensión) | `src/tf/permissions.py` | G1 |
| Model Gateway tipado (generative vs evaluator — Jev) | `src/tf/gateway.py` | §7.1 |
| Esqueleto de agente: heartbeat, publicación por broker, herramientas auditadas | `src/tf/agents.py` | G1/G2/G5 |
| Audit log inmutable con hash encadenado | `src/tf/audit.py` | Auditoría (§5) |
| Esquema de memoria colectiva (Postgres + Timescale + pgvector) | `migrations/0001_init.sql` | §5 |
| Guardarraíles declarativos de los 13 agentes | `config/guardrails.yaml` | G1/G4 |
| Asignación de modelos por agente | `config/models.yaml` | §7.1 |

## Cómo ejecutar

```bash
uv sync                      # instala dependencias (pydantic, pyyaml, pytest)
uv run pytest -q             # 32 tests: contratos, cadena de hash, permisos, gateway, agentes

# Infraestructura (Postgres+Timescale con migraciones y NATS con JetStream):
docker compose up -d
```

## Diseño clave fijado en código

1. **Nada entra al bus sin cumplir su contrato**: `InMemoryBus.publish` valida el payload
   contra el registro de tipos; la misma política irá en el adaptador NATS.
2. **Toda publicación y toda herramienta pasan por el broker**: un agente suspendido
   no publica (salvo su heartbeat, que es la señal de salud y sale en `degraded`).
3. **Audit log a prueba de manipulación**: cada entrada encadena el hash de la anterior;
   borrar o editar cualquier entrada rompe la verificación de la cadena (test incluido).
4. **Modelos = configuración**: el gateway rechaza en arranque asignaciones incoherentes
   (un `evaluator` sin id externo, un `decisions` apuntando a un generativo) y admite
   agentes deterministas sin modelo (`execution-router`).

## Siguientes pasos (Fase 1)

1. Adaptador NATS JetStream de `BaseBus` (misma interfaz, misma validación en el borde).
2. Implementación Postgres de `AuditLog` (el hash encadenado ya está probado).
3. Proveedores reales en el Model Gateway (generativos vía API; Jev vía `ai` SDK/Vercel
   AI Gateway para las decisiones estructuradas).
4. Motor de backtest vectorizado + primera versión de `research-hypothesis` y
   `backtest-engineer` para cerrar el primer ciclo Research → Backtest.
