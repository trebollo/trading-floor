"use client";

// Panel de la Wall: la vista detallada de la memoria operativa que se
// proyecta en la pantalla norte de la oficina. Se abre al hacer clic en ella.

import { EquityChart } from "@/components/EquityChart";
import { eur, pct, relativo } from "@/lib/format";
import type { OficinaData } from "@/lib/oficina";

const NIVEL_PUNTO = {
  info: "bg-emerald-400",
  aviso: "bg-amber-400",
  critico: "bg-rose-400",
} as const;

function TarjetaKpi({ etiqueta, valor, detalle }: { etiqueta: string; valor: string; detalle?: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-borde)] p-3">
      <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">{etiqueta}</p>
      <p className="mt-0.5 text-lg font-semibold text-zinc-100">{valor}</p>
      {detalle && <p className="text-[11px] text-zinc-600">{detalle}</p>}
    </div>
  );
}

export function WallPanel({ datos, onCerrar }: { datos: OficinaData; onCerrar: () => void }) {
  const k = datos.kpis;
  const deptos = [...datos.departamentos].sort((a, b) => b.pnlDia - a.pnlDia);
  const maxAbsPnl = Math.max(...deptos.map((d) => Math.abs(d.pnlDia)), 1);
  const dd = datos.equity.length > 0 ? datos.equity[datos.equity.length - 1].drawdownPct : 0;

  return (
    <aside
      className="absolute right-0 top-0 z-10 flex h-full w-full max-w-sm flex-col border-l border-[var(--color-borde)] bg-[var(--color-lienzo)]/92 backdrop-blur"
      style={{ borderRight: "2px solid rgba(52,211,153,0.4)" }}
    >
      <header className="flex items-start gap-3 border-b border-[var(--color-borde)] p-4">
        <span className="mt-1 inline-block h-3 w-3 rounded-full bg-emerald-400" />
        <div className="flex-1">
          <h2 className="text-base font-semibold">Memoria operativa</h2>
          <p className="text-xs text-zinc-500">Lo que la Wall proyecta, con el detalle completo</p>
        </div>
        <button
          type="button"
          onClick={onCerrar}
          className="rounded-lg border border-[var(--color-borde)] px-2 py-1 text-xs text-zinc-400 hover:bg-white/5"
        >
          ✕
        </button>
      </header>

      <div className="flex-1 space-y-5 overflow-y-auto p-4">
        {/* KPIs */}
        <section className="grid grid-cols-2 gap-2">
          <TarjetaKpi etiqueta="P&L hoy" valor={eur(k.pnlDia)} detalle="sesión en curso" />
          <TarjetaKpi etiqueta="P&L acumulado" valor={eur(k.pnlAcumulado)} detalle="desde el origen" />
          <TarjetaKpi etiqueta="Exposición" valor={pct(k.exposicionPct)} detalle="sobre capital" />
          <TarjetaKpi etiqueta="Presupuesto LLM" valor={pct(k.presupuestoUsadoPct)} detalle="ciclo mensual" />
          <TarjetaKpi etiqueta="Estrategias vivas" valor={String(k.estrategiasVivas)} detalle={`modo ${k.modo}`} />
          <TarjetaKpi etiqueta="Drawdown" valor={pct(dd)} detalle="sobre la curva de equity" />
        </section>

        {/* Curva de equity */}
        <section>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Curva de equity</h3>
          <div className="rounded-lg border border-[var(--color-borde)] p-2">
            <EquityChart puntos={datos.equity} altura={200} />
          </div>
        </section>

        {/* P&L por departamento */}
        <section>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
            P&L de hoy por departamento
          </h3>
          <ul className="space-y-1.5">
            {deptos.map((d) => {
              const positivo = d.pnlDia >= 0;
              const anchura = (Math.abs(d.pnlDia) / maxAbsPnl) * 50;
              return (
                <li key={d.id} className="flex items-center gap-2 text-xs">
                  <span className="w-28 shrink-0 truncate text-zinc-400">{d.nombre}</span>
                  <div className="relative h-4 flex-1">
                    <div className="absolute left-1/2 top-0 h-full w-px bg-[var(--color-borde)]" />
                    <div
                      className="absolute top-0.5 h-3 rounded-sm"
                      style={{
                        background: d.color,
                        opacity: 0.75,
                        left: positivo ? "50%" : `${50 - anchura}%`,
                        width: `${anchura}%`,
                      }}
                    />
                  </div>
                  <span className={`w-20 shrink-0 text-right font-mono ${positivo ? "text-emerald-300" : "text-rose-300"}`}>
                    {positivo ? "+" : ""}
                    {d.pnlDia.toFixed(0)} €
                  </span>
                </li>
              );
            })}
          </ul>
        </section>

        {/* Alertas */}
        <section>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
            Alertas de la sesión ({datos.alertas.length})
          </h3>
          <ul className="space-y-2">
            {datos.alertas.map((a, i) => (
              <li key={i} className="flex items-start gap-2 rounded-lg border border-[var(--color-borde)] p-2.5 text-xs">
                <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${NIVEL_PUNTO[a.nivel]}`} />
                <div>
                  <p className="text-zinc-300">{a.texto}</p>
                  <p className="text-[11px] text-zinc-600">{relativo(a.ts)}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </aside>
  );
}
