# Trading Floor

Sistema multiagente de trading algorítmico autónomo, organizado como una empresa digital:
departamentos especializados que se comunican por un bus de eventos, con riesgo como
barrera absoluta y el CEO como única autoridad humana de gobierno.

## Documentación

- [Arquitectura del sistema](docs/arquitectura.md) — diseño completo: departamentos,
  agentes, comunicación, memoria colectiva, ciclo de vida de una estrategia, stack,
  hoja de ruta y KPIs.

## Resumen en una frase

Agentes de IA proponen estrategias; un pipeline determinista (backtest → validación
Monte Carlo/walk-forward → comité de riesgos) decide qué sobrevive; el portfolio se opera
automáticamente dentro de límites duros, y todo queda registrado en una memoria colectiva
auditable que alimenta el siguiente ciclo de investigación.

## Departamentos

| Departamento | Función |
|---|---|
| Dirección (Executive Suite) | Directrices del CEO, informes, presupuestos |
| Research Lab | Generación de hipótesis y especificaciones de estrategias |
| Backtest Dept | Evaluación histórica objetiva con costes realistas |
| Validation Dept | Monte Carlo, walk-forward, estrés de regímenes, adversario dedicado |
| Risk Dept | Gate pre-trade y riesgo de portfolio; veto absoluto |
| Execution & Ops | Ejecución de órdenes, reconciliación, contabilidad |
| Macro & News | Regímenes de mercado, noticias, calendario económico |

Los modelos de cada agente son **intercambiables por configuración** a través de un Model
Gateway. Para las decisiones estructuradas (triaje, clasificación, puntuación de rubrics)
se usa **Jev** (`typesafe-ai/jev`, modelo de evaluación de TypeSafe AI vía Vercel AI
Gateway): rápido, ~$0.042/M tokens y sin generación de texto; la redacción corre a cargo de
modelos generativos ligeros por rol (ver
[docs/arquitectura.md §7.1](docs/arquitectura.md#71-capa-de-modelos-intercambiables-model-gateway)).

## Estado

Fase de diseño. La hoja de ruta de implementación (Fase 0–4) está en
[docs/arquitectura.md §10](docs/arquitectura.md#10-hoja-de-ruta-por-fases).
