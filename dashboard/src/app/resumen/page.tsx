import { getOverview } from "@/lib/data";
import { eur, pct, relativo } from "@/lib/format";
import { PageHeader, Panel, StatCard } from "@/components/ui";
import { EquityChart } from "@/components/EquityChart";
import { ModeSwitch } from "@/components/ModeSwitch";

// Despliegue serverless: regeneración incremental cada 20 s.
export const revalidate = 20;

const NIVEL_ESTILO = {
  info: "border-sky-500/30 bg-sky-500/5 text-sky-200",
  aviso: "border-amber-500/30 bg-amber-500/5 text-amber-200",
  critico: "border-rose-500/30 bg-rose-500/5 text-rose-200",
} as const;

const ESTADO_PUNTO = {
  operativo: "bg-emerald-400",
  ocupado: "bg-sky-400",
  degradado: "bg-amber-400",
  pausado: "bg-zinc-500",
} as const;

export default async function ResumenPage() {
  const { datos, fuente } = await getOverview();
  const { kpis, equity, alertas, departamentos } = datos;
  const pnlDiaPositivo = kpis.pnlDia >= 0;

  return (
    <>
      <PageHeader
        titulo="Resumen operativo"
        descripcion="Telemetría del sistema multiagente en vista clásica: cartera operada, alertas y departamentos."
        fuente={fuente}
        acciones={<ModeSwitch modoActual={kpis.modo} />}
      />

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-5">
        <StatCard
          etiqueta="P&L hoy"
          valor={`${pnlDiaPositivo ? "+" : ""}${eur(kpis.pnlDia)}`}
          tono={pnlDiaPositivo ? "positivo" : "negativo"}
        />
        <StatCard
          etiqueta="P&L acumulado"
          valor={`${kpis.pnlAcumulado >= 0 ? "+" : ""}${eur(kpis.pnlAcumulado)}`}
          detalle={`Capital ${eur(kpis.capital)}`}
          tono={kpis.pnlAcumulado >= 0 ? "positivo" : "negativo"}
        />
        <StatCard
          etiqueta="Exposición bruta"
          valor={pct(kpis.exposicionPct)}
          detalle="Límite vigente: 60 %"
          tono={kpis.exposicionPct > 60 ? "aviso" : "neutral"}
        />
        <StatCard etiqueta="Estrategias vivas" valor={String(kpis.estrategiasVivas)} detalle="de 7 en el ciclo" />
        <StatCard
          etiqueta="Presupuesto LLM"
          valor={pct(kpis.presupuestoUsadoPct)}
          detalle="Techo: 5 €/día (G3)"
          tono={kpis.presupuestoUsadoPct > 80 ? "aviso" : "neutral"}
        />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Panel titulo="Curva de equity (trading en papel)" className="xl:col-span-2">
          <EquityChart puntos={equity} />
        </Panel>

        <Panel titulo="Alertas">
          <ul className="space-y-2.5">
            {alertas.length === 0 && <li className="text-sm text-zinc-600">Sin alertas.</li>}
            {alertas.map((a) => (
              <li key={a.id} className={`rounded-lg border px-3 py-2 text-sm ${NIVEL_ESTILO[a.nivel]}`}>
                {a.texto}
                <span className="mt-0.5 block text-[11px] text-zinc-500">{relativo(a.ts)}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <div className="mt-6">
        <Panel titulo="Departamentos">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {departamentos.map((d) => (
              <div key={d.departamento} className="rounded-lg border border-[var(--color-borde)] p-3">
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${ESTADO_PUNTO[d.estado]}`} />
                  <p className="text-sm font-medium text-zinc-200">{d.departamento}</p>
                  <span className="ml-auto text-[11px] text-zinc-600">{d.agentes} agentes</span>
                </div>
                <p className="mt-1.5 text-xs text-zinc-500">{d.detalle}</p>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}
