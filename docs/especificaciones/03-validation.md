# Especificación: Validation Department

*Guardarraíles transversales: ver [00-marco-guardarrailes.md](00-marco-guardarrailes.md).*

## 1. Misión y alcance

Someter las estrategias promovidas por Backtest a baterías avanzadas de estrés y emitir
`VALIDADA | RECHAZADA`. Es el último filtro estadístico antes del Risk Dept. Trabaja con
independencia deliberada de Research y Backtest.

## 2. Agentes

### 2.1 `validation-quant` (×1)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Ejecutar la batería canónica (§3) y consolidar resultados en el veredicto |
| Modelo | Generativo `frontier-strong` + `decisions: jev` |
| Herramientas (G1) | `run_monte_carlo`, `run_walk_forward`, `run_regime_stress`, `run_param_sensitivity`, `run_cost_robustness`, `read_spec`, `publish_verdict` |
| Publica | `validation.verdict.v1`, `validation.battery_log.v1` |

### 2.2 `validation-skeptic` (×1, adversario)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Intentar derribar la estrategia: diseñar escenarios adversos adicionales fuera de la batería canónica |
| Modelo | Generativo `frontier-strong` |
| Herramientas (G1) | `read_spec`, `read_battery_results`, `propose_adversarial_scenario` (pasa por validador de esquema y de factibilidad), `publish_skeptic_report` |
| Publica | `validation.skeptic_report.v1` |

## 3. Batería canónica (invariable, fijada por política — no por los agentes)

1. **Monte Carlo:** ≥ 10.000 permutaciones de reordenación de trades + bootstrap de
   bloques; el percentil 5 del capital final debe ser positivo y el P5 del drawdown debe
   caber en el contrato de riesgo.
2. **Walk-forward:** ventanas deslizantes optimizar→validar; degradation ratio
   in-sample/out-of-sample ≥ umbral del CEO (por defecto 0.5).
3. **Estrés de régimen:** evaluación forzada en los regímenes etiquetados por Macro & News;
   prohibido promocionar si el P25 de retorno en régimen adverso < umbral.
4. **Sensibilidad:** ±20 % en cada parámetro; el signo del retorno no puede invertirse en
   la meseta central.
5. **Robustez de costes:** ×2 slippage supuesto mantiene viabilidad.
6. **Correlación con portfolio:** incremento de riesgo correlacionado con estrategias
   vivas dentro del límite fijado por Risk (datos que Risk publica para este fin).

Un veredicto `VALIDADA` exige superar los 6 puntos. La batería se ejecuta siempre igual;
los umbrales viven en configuración del CEO, no en decisiones de los agentes.

## 4. Guardarraíles específicos

| # | Guardarrail | Tipo |
|---|---|---|
| V-1 | **Batería invariable:** ningún agente puede saltarse, reordenar o "simplificar" pruebas; la ejecución parcial invalida el veredicto (checklist firmada por el orquestador, no por el LLM) | G5 |
| V-2 | **Independencia de información:** Validation no ve el detalle de la exploración de Research (solo el spec congelado y el resumen de Backtest) para evitar anclaje; los agentes no comparten memoria de sesión con otros departamentos | G4 |
| V-3 | **El skeptic no aprueba:** sus informes solo pueden añadir evidencia negativa o neutra; un `VALIDADA` requiere que los 6 puntos canónicos pasen aunque el skeptic no encuentre nada | G5 |
| V-4 | **Escenarios del skeptic tipados:** todo escenario adverso pasa validador de factibilidad (universo permitido, horizonte acotado, coste de cómputo acotado); sin límite de presupuesto no se ejecuta | G2/G3 |
| V-5 | **Ciego estructural:** los agentes de Validation no pueden lanzar corridas sobre el test ciego directamente; el orquestador lo hace y solo expone métricas agregadas | G4/G5 |
| V-6 | **Cuota de escenarios:** el skeptic debe presentar ≥ 5 escenarios, incluido ≥ 1 de cola (pérdida > 5 % del capital simulado) antes de que se considere completa su evaluación | G5 |
| V-7 | **Veredicto binario y motivado:** `VALIDADA|RECHAZADA` + mapeo punto a punto de la batería; no existe "validada con reservas" (las reservas van al contrato de riesgo que propone Risk) | G5 |
| V-8 | **Re-validación obligatoria:** toda estrategia viva re-pasa la batería cada 90 días o cuando drift detection lo dispare; Validation no decide si re-validar, la política sí | G5 |

## 5. Modos de fallo y degradación

- **Cualquier herramienta de batería caída:** la propuesta queda en `VALIDATION_PENDING`,
  nunca se promociona por plazo (fail-closed).
- **Skeptic caído:** la evaluación no se considera completa; puede avanzar a Risk solo
  como `VALIDADA_PROVISIONAL` con capital papel exclusivamente, hasta informe del skeptic.
- **Datos de régimen ausentes** (Macro sin publicar): los puntos 3 y 6 de la batería no
  pueden evaluarse ⇒ veredicto máximo `VALIDADA_PROVISIONAL`.

## 6. KPIs del departamento

Estrategias validadas/semana · tasa de derribo del skeptic (aporte real del adversario) ·
correlación entre veredicto y rendimiento real posterior (la métrica de calibración más
importante del sistema) · coste de cómputo por veredicto.
