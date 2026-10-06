"use client";

// Panel de la Wall: vista detallada de la memoria operativa que se proyecta
// en la pantalla norte de la oficina. Se abre al hacer clic en ella.

import { EquityChart } from "@/components/EquityChart";
import { KpiWall } from "@/components/KpiWall";
import { relativo } from "@/lib/format";
import type { OficinaData } from "@/lib/oficina";

const NIVEL_PUNTO = {
  info: "bg-emerald-400",
  aviso: "bg-amber-400",
  critico: "bg-rose-400",
} as const;

const NIVEL_TEXTO = {
  info: "text-emerald-300",
  aviso: "text-amber-300",
  critico: "text-rose-300",
} as const;

export function WallPanel({ datos, onCerrar }: { datos: OficinaData; onCerrar: () => void }) {
  const deptos = [...datos.departamentos].sort((a, b) => b.pnlDia - a.pnlDia);
  const maxAbsPnl = Math.max(...deptos.map((d) => Math.abs(d.pnlDia)), 1);

  return (
    <aside
      className="absolute right-0 top-0 z-10 flex h-full w-full max-w-md flex-col border-l border-[var(--color-borde)] bg-[var(--color-lienzo)]/94 backdrop-blur-xl"
      style={{ borderRight: "2px solid rgba(52,211,153,0.45)" }}
    >
      <header className="flex items-start gap-3 border-b border-[var(--color-borde)] p-4">
        <span className="mt-1 inline-block h-3 w-3 rounded-full bg-emerald-400 shadow-[0_0_12px_rgba(52,211,153,0.8)]" />
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
        <section>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Indicadores clave</h3>
          <KpiWall kpis={datos.kpis} equity={datos.equity} />
        </section>

        <section>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
            Curva de equity · drawdown
          </h3>
          <div className="rounded-xl border border-[var(--color-borde)] bg-black/30 p-2">
            <EquityChart puntos={datos.equity} altura={220} />
          </div>
          <div className="mt-1.5 flex items-center gap-3 px-1 text-[10px] text-zinc-500">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-400" /> Equity
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-rose-400/80" /> Drawdown %
            </span>
          </div>
        </section>

        <section>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
            P&amp;L de hoy por departamento
          </h3>
          <ul className="space-y-1.5">
            {deptos.map((d) => {
              const positivo = d.pnlDia >= 0;
              const anchura = (Math.abs(d.pnlDia) / maxAbsPnl) * 50;
              return (
                <li
                  key={d.id}
                  className="flex items-center gap-2 rounded-lg border border-transparent px-1 py-0.5 text-xs transition-colors hover:border-[var(--color-borde)] hover:bg-white/[0.02]"
                >
                  <span className="w-28 shrink-0 truncate text-zinc-400">{d.nombre}</span>
                  <div className="relative h-4 flex-1">
                    <div className="absolute left-1/2 top-0 h-full w-px bg-[var(--color-borde)]" />
                    <div
                      className="absolute top-0.5 h-3 rounded-sm shadow-[0_0_8px_currentColor]"
                      style={{
                        background: d.color,
                        color: d.color,
                        opacity: 0.85,
                        left: positivo ? "50%" : `${50 - anchura}%`,
                        width: `${Math.max(anchura, 0.8)}%`,
                      }}
                    />
                  </div>
                  <span
                    className={`w-20 shrink-0 text-right font-mono tabular-nums ${
                      positivo ? "text-emerald-300" : "text-rose-300"
                    }`}
                  >
                    {positivo ? "+" : ""}
                    {d.pnlDia.toFixed(0)} €
                  </span>
                </li>
              );
            })}
          </ul>
        </section>

        <section>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
            Alertas de la sesión ({datos.alertas.length})
          </h3>
          <ul className="space-y-2">
            {datos.alertas.map((a, i) => (
              <li
                key={i}
                className="flex items-start gap-2 rounded-xl border border-[var(--color-borde)] bg-black/25 p-2.5 text-xs"
              >
                <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${NIVEL_PUNTO[a.nivel]}`} />
                <div className="min-w-0">
                  <p className={`text-[11px] font-medium uppercase tracking-wide ${NIVEL_TEXTO[a.nivel]}`}>
                    {a.nivel}
                  </p>
                  <p className="mt-0.5 text-zinc-300">{a.texto}</p>
                  <p className="mt-0.5 text-[11px] text-zinc-600">{relativo(a.ts)}</p>
                </div>
              </li>
            ))}
            {datos.alertas.length === 0 && (
              <li className="rounded-xl border border-dashed border-[var(--color-borde)] p-3 text-center text-xs text-zinc-600">
                Sin alertas en la sesión.
              </li>
            )}
          </ul>
        </section>
      </div>
    </aside>
  );
}
