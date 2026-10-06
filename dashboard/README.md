# Trading Floor — Dashboard CEO

UI web de gobierno y observabilidad del sistema multiagente. Implementa el
"Dashboard CEO" previsto en [docs/arquitectura.md §3.7](../docs/arquitectura.md#37-dirección-executive-suite).

## Stack

- **Next.js 15** (App Router, Server Components y Server Actions) + **React 19** + TypeScript.
- **Tailwind CSS v4** para el tema oscuro.
- **Three.js** para la escena isométrica low-poly de la planta (`/`): orthographic camera 2:1,
  salas de cristal, agentes facetados y skyline de fondo. Se carga con import dinámico
  (solo cliente) para no inflar el bundle del server render.
- **Recharts 3** para la telemetría visual (equity + drawdown; base de los gráficos
  avanzados futuros: velas de `market_data`, distribuciones Monte Carlo, etc.).
- **postgres.js** con pool bajo, apto para despliegue serverless (Vercel) contra el
  pooler de Neon/Supabase apuntando a la memoria colectiva (migraciones en `migrations/`).

## Vistas

| Ruta | Contenido |
|---|---|
| `/` | **La Oficina**: planta isométrica low-poly en Three.js con los 7 departamentos como salas de cristal, agentes en sus mesas y la *wall* norte proyectando KPIs y equity. HUD con chips de navegación, ticker inferior filtrable por sala y paneles laterales (plantilla, estrategias con acciones, memoria operativa con equity+drawdown y P&L por departamento). Arrastrar/rueda para navegar. En modo demo, una simulación en vivo hace respirar la escena |
| `/resumen` | KPIs (P&L, exposición, presupuesto LLM), curva de equity, alertas, estado de departamentos, conmutador de modo del sistema |
| `/estrategias` | Catálogo con ciclo de vida y acciones (pausar/retirar/bloquear) con doble confirmación |
| `/pipeline` | Embudo de investigación por etapa y evaluaciones recientes |
| `/riesgo` | Gate pre-trade, vetos recientes y límites vigentes (solo lectura) |
| `/directivas` | Consola de directrices del CEO: publicar y revocar |
| `/auditoria` | Log de eventos con hash encadenado |

Toda acción de gobierno exige **doble confirmación** (principios P2/P4 de la
arquitectura) y, con base de datos, queda registrada en la memoria colectiva.

## Desarrollo

```bash
pnpm install
pnpm dev            # puerto 3100
pnpm build && pnpm start
pnpm typecheck
```

Sin `DATABASE_URL` la app arranca en **modo demo** (datos de ejemplo, acciones
simuladas y etiquetadas). Con `DATABASE_URL` lee las tablas reales
(`strategies`, `evaluations`, `directives`, `risk_checks`, `audit_log`); copia
`.env.example` a `.env` para configurarla.

## Limitaciones conocidas (hacia fase 4)

- La curva de equity y los KPIs de P&L usan datos de demo: la serie de P&L aún no
  existe como tabla (telemetría de fase 4).
- Los límites de riesgo se muestran como espejo de `config/guardrails.yaml`; su
  edición desde la web se aplicará vía directriz auditable con validación.
- **Gobernanza en modo live sin desplegar todavía**: las Server Actions ya validan
  el ciclo de vida de las estrategias (transiciones permitidas con
  compare-and-swap) pero **no hay autenticación ni autorización del CEO**, ni
  registro en `audit_log` de las mutaciones, y el cambio de modo solo publica una
  directriz sin confirmación de aplicación. Con `DATABASE_URL` configurado, el
  dashboard debe quedar detrás del SSO/proxy del CEO y sin acceso público hasta
  integrar autenticación y auditoría.
- El refresco es por regeneración incremental (20 s); el streaming en vivo desde
  NATS llegaría con la API de plataforma de la fase 4.
