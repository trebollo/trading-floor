# Especificación: Dirección (Executive Suite)

*Guardarraíles transversales: ver [00-marco-guardarrailes.md](00-marco-guardarrailes.md).*

## 1. Misión y alcance

Ser la interfaz de gobierno entre el CEO y la organización digital: traducir directrices
en tareas, sintetizar el estado de los departamentos, escrutar solicitudes y ejecutar las
decisiones humanas. **La Dirección no opera ni decide trading**; gobierna el marco en que
los demás deciden.

## 2. Agentes y componentes

### 2.1 `chief-of-staff` (×1)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Informe diario para el CEO; escrutinio de solicitudes de departamentos (presupuestos, cambios de límites, aperturas de familias bloqueadas); traducción de directrices en tareas; seguimiento de su cumplimiento |
| Modelo | Generativo `frontier-strong` (síntesis) + `decisions: jev` (priorización de solicitudes y alertas) |
| Herramientas (G1) | `read_all_reports` (lectura amplia, sin secretos), `search_memory`, `read_directives`, `publish_task`, `submit_ceo_action` (encola para firma humana), `read_queue_state` |
| Publica | `executive.daily_report.v1`, `executive.task.v1`, `executive.ceo_request.v1` |

### 2.2 Dashboard CEO (UI + API de gobierno)

P&L y exposición en vivo · pipeline de investigación · estrategias vivas y su contrato ·
incidentes y violaciones de guardarraíles · consola de directrices · botones de
aprobación con doble confirmación · kill switch global y por departamento.

## 3. Poderes humanos y su mecanismo

| Acción del CEO | Mecanismo |
|---|---|
| Desplegar estrategia validada (papel o capital) | Firma en dashboard; Risk crea el contrato de riesgo; ejecución automática |
| Cambiar límites de riesgo / presupuestos | Doble confirmación; cambio versionado; efecto inmediato en el gate |
| Modo del sistema (PAPER / REDUCIDO / LIVE) | Doble confirmación |
| Directriz estratégica (texto libre) | `directive.new` versionada; chief-of-staff la descompone en tareas; su cumplimiento se mide |
| Pausar/retirar estrategia o departamento | Inmediato; con opciones de solo-cierre |
| Reabrir familia de estrategias bloqueada (R-5) | Única vía para anular R-5 |

## 4. Guardarraíles específicos

| # | Guardarrail | Tipo |
|---|---|---|
| D-1 | **El chief-of-staff no firma nada:** todas las acciones de gobierno pasan por `submit_ceo_action`, que queda esperando la firma humana; no existe flujo "el agente actuó y luego avisó" | G7 |
| D-2 | **Acciones críticas con doble confirmación** (límites, modo del sistema, kill switch): requiere dos gestos distintos del CEO en un intervalo acotado | G7 |
| D-3 | **No puede saltarse el pipeline:** ninguna directriz puede ordenar ejecutar una estrategia sin validación vigente ni una orden sin risk_token; la plataforma rechaza la tarea en el validador de tareas | G5 |
| D-4 | **Directrices versionadas e interpretación acotada:** el chief-of-staff traduce directrices a tareas publicadas (auditables); no puede reinterpretar una directriz de forma no trazable a su texto | G5 |
| D-5 | **Lectura amplia, escritura mínima:** lee todos los informes y métricas, pero sus escrituras se reducen a tareas, directrices y solicitudes de firma — nunca a estado de negocio | G4 |
| D-6 | **Síntesis con trazas:** cada cifra del informe diario enlaza a su fuente (mensaje o evaluación); una cifra sin fuente se marca `UNVERIFIED` y no entra al resumen ejecutivo | G5 |
| D-7 | **Cuota de intervenciones:** máx. N solicitudes de firma al día al CEO (anti-fatiga); el exceso obliga a priorizar, no a bombardear | G5 |
| D-8 | **Sin secretos:** ni el agente ni el dashboard exponen credenciales; el dashboard opera contra la API con autenticación del CEO | G6 |

## 5. Modos de fallo y degradación

- **Chief-of-staff caído:** los departamentos siguen funcionando (no dependen de él);
  el informe diario se retrasa; las firmas quedan pendientes en el dashboard, que no
  depende del agente.
- **Dashboard caído:** el kill switch de emergencia vive fuera del dashboard (CLI de
  plataforma y endpoint directo al bus) para que ninguna caída de UI impida parar el
  sistema.

## 6. KPIs del departamento

Cumplimiento de directrices (% tareas cerradas) · tiempo de escrutinio de solicitudes ·
calidad del informe diario (cifras verificadas / total) · nº de firmas pedidas vs.
necesarias · tiempo CEO→efecto para cambios críticos.
