# Marco de guardarraíles para agentes

*Aplica a todos los departamentos. Cada especificación de departamento añade sus
guardarraíles específicos sobre este marco.*

## 1. Las siete clases de guardarraíl

| Clase | Qué controla | Dónde se aplica |
|---|---|---|
| **G1 · Permisos de herramientas** | Qué puede *hacer* el agente: lista cerrada de herramientas, sin llamadas libres | Permission Broker: toda llamada a herramienta pasa por él; lo que no está en la lista no existe para el agente |
| **G2 · Entrada/salida tipada** | Qué forma tienen los mensajes y respuestas | Esquemas JSON versionados validados en el borde del bus; salida inválida = rechazo + registro |
| **G3 · Presupuesto** | Cuánto puede gastar: tokens, peticiones, cómputo, coste € | Model Gateway y orquestador; corte automático y degradación a modelo económico |
| **G4 · Alcance de datos** | Qué puede *leer*: dominios de memoria, datasets, redacciones | Etiquetas de acceso por dominio en la memoria colectiva; el gateway de datos filtra por rol |
| **G5 · Comportamentales** | Qué puede *decidir*: límites de frecuencia, rubrics obligatorias, prohibiciones semánticas | Reglas + evaluador (Jev) sobre las salidas antes de publicar |
| **G6 · Seguridad** | Sandbox, red, secretos, código ejecutado | Contenedores sin red, volúmenes de solo lectura, secretos nunca en prompts ni contexto |
| **G7 · Escalado humano** | Cuándo parar y avisar al CEO | Clasificación de eventos; acción reversible → automática; irreversible → pausa + aprobación |

## 2. Reglas transversales (todos los agentes, sin excepción)

1. **Sin estado propio.** Ningún agente persiste contexto entre tareas; todo lo que debe
   sobrevivir se escribe en la memoria colectiva vía eventos. Un agente reiniciado pierde
   cero información de negocio.
2. **Escritura solo por eventos.** Ningún agente escribe tablas de negocio directamente:
   publica mensajes; los servicios de plataforma materializan el estado. Esto hace cada
   mutación auditable y reproducible.
3. **Salida tipada o nada.** Si la respuesta no cumple el esquema del mensaje, no se
   publica: se registra como `agent.output_invalid` y cuenta para la métrica de calidad
   del modelo asignado.
4. **Toda decisión lleva motivo.** El campo `rationale` es obligatorio en los mensajes de
   decisión (veredictos, prioridades, alertas) y se indexa en el audit log.
5. **Idempotencia.** Toda acción con efecto externo lleva `idempotency_key` derivada de
   la causa; reintentos no duplican efectos.
6. **Identidad en todo mensaje.** `actor` = agente + rol + modelo usado + versión de
   prompt. Un cambio de modelo no cambia permisos, pero sí queda registrado.
7. **Prohibición de abstracción de autoridad.** Ningún agente puede invocar "el CEO
   mandaría" o reinterpretar directrices fuera del registro de directrices vigente.

## 3. Configuración declarativa

Los guardarraíles se declaran por agente en `config/guardrails.yaml` y se validan al
arrancar (una configuración inválida impide el arranque del agente, no se ignora):

```yaml
agent: risk-portfolio
tools: [read_portfolio_state, read_market_data, read_risk_limits]   # G1: lista cerrada
data_domains: [portfolio, market, risk_limits, evaluations]         # G4
budget:
  tokens_per_hour: 500_000        # G3
  eur_per_day: 5.0
  compute_minutes_per_hour: 10
output_contracts: [risk.assessment.v1, risk.portfolio_review.v1]    # G2
behavioural:                                                        # G5
  max_actions_per_hour: 60
  forbidden: [publish_order_request, modify_limits, deploy_strategy]
  required_rubrics: [risk_rubric_v2]
escalation:                                                         # G7
  pause_on: [data_domain_violation, budget_exceeded_3x]
  notify_ceo_on: [limit_breach_detected, reconciliation_mismatch]
```

## 4. Enforcement en capas (defensa en profundidad)

```
petición del agente
      │
      ▼
┌─────────────────────┐  G1 ¿herramienta permitida?  G4 ¿dominio de datos permitido?
│ Permission Broker   │── no ──► rechazo + audit log + contador de violación
└─────────┬───────────┘
          ▼
┌─────────────────────┐  G6 ¿el destino necesita red/secretos que el agente no tiene?
│ Herramienta real    │
└─────────┬───────────┘
          ▼
┌─────────────────────┐  G2 ¿esquema válido?  G5 ¿rubric/prohibición cumplida?
│ Validador de salida │── no ──► agent.output_invalid (nunca publica)
└─────────┬───────────┘
          ▼
   Event Bus  ──► audit log inmutable (todo lo anterior también se registra)
```

Ninguna capa confía en la anterior: un agente no puede "saltarse" el validador de salida
escribiendo directo al bus, porque el bus también valida.

## 5. Taxonomía de violaciones y respuesta graduada

| Nivel | Ejemplos | Respuesta automática |
|---|---|---|
| **V1 · Aviso** | Salida inválida aislada, presupuesto al 80 % | Registrar, avisar al departamento, seguir |
| **V2 · Contención** | Salidas inválidas repetidas, exceso de frecuencia, presupuesto agotado | Throttle del agente, degradación de modelo, reencolado de tareas |
| **V3 · Suspensión** | Violación de dominio de datos, intento de herramienta prohibida, patrón anómalo (p. ej. decisões fuera de distribuciones esperadas) | Pausa del agente, sus tareas pasan a otro agente del departamento, incidente en el dashboard |
| **V4 · Escalado al CEO** | Acción irreversible sin autorización, discrepancy de posiciones, límite de riesgo roto por cualquier causa | Pausa del departamento o del sistema (modo solo-cierre), notificación inmediata |

Toda violación genera `lesson` candidata: los guardarraíles evolucionan con el sistema.

## 6. Verificación de guardarraíles (los guardarraíles también se testan)

- **Suite de pruebas de permisos:** por cada agente, una batería que intenta cada
  herramienta prohibida y verifica el rechazo; corre en CI.
- **Caos de presupuesto:** simulación de agente desbocado; verificar contención V2/V3.
- **Replay de decisiones:** semanalmente se repasan decisiones reales contra las reglas
  actuales; cualquier decisión que las reglas actuales contradigan se marca para revisión.
- **Canary de fail-closed:** se inyectan fallos (Jev caído, bus lento, datos corruptos) y se
  verifica que el sistema falla cerrando (rechaza/pausa), nunca abriendo.
