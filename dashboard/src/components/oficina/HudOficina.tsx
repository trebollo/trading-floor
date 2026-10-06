"use client";

// HUD superior de la oficina: contexto de sesión + chips de navegación.

import type { DeptoOficina, OficinaData } from "@/lib/oficina";
import { FuenteBadge } from "@/components/ui";

export function HudOficina({
  datos,
  deptoSel,
  wallSel,
  onIrGeneral,
  onIrWall,
  onIrDepto,
}: {
  datos: OficinaData;
  deptoSel: string | null;
  wallSel: boolean;
  onIrGeneral: () => void;
  onIrWall: () => void;
  onIrDepto: (id: string) => void;
}) {
  const modo = datos.kpis.modo;
  const modoColor =
    modo === "LIVE" ? "text-rose-300 border-rose-500/40 bg-rose-500/10" : modo === "PAPER" ? "text-amber-300 border-amber-500/40 bg-amber-500/10" : "text-sky-300 border-sky-500/40 bg-sky-500/10";

  const chipBase =
    "rounded-lg border px-2.5 py-1 text-[11px] backdrop-blur transition-colors";
  const chipOff = "border-[var(--color-borde)] bg-black/60 text-zinc-300 hover:bg-black/80";

  return (
    <div className="pointer-events-auto absolute left-4 top-4 z-10 max-w-[320px] space-y-3">
      <div className="rounded-xl border border-[var(--color-borde)] bg-black/55 p-3 backdrop-blur-md">
        <div className="flex items-start gap-2">
          <div className="flex-1">
            <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">Sesión operativa</p>
            <p className="mt-0.5 text-sm font-semibold text-zinc-100">Planta del trading floor</p>
            <p className="mt-1 text-[11px] leading-relaxed text-zinc-400">
              Vigila salas, agentes y la memoria operativa. Cada acción de gobierno exige doble confirmación.
            </p>
          </div>
          <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${modoColor}`}>
            {modo}
          </span>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <FuenteBadge fuente={datos.fuente} />
          <span className="text-[10px] text-zinc-600">
            {datos.kpis.estrategiasVivas} vivas · {datos.eventos.length} eventos
          </span>
        </div>
      </div>

      <div className="flex max-w-[290px] flex-wrap gap-1.5">
        <button
          type="button"
          onClick={onIrGeneral}
          className={`${chipBase} ${
            !deptoSel && !wallSel
              ? "border-emerald-400/50 bg-emerald-400/10 text-emerald-200"
              : chipOff
          }`}
        >
          Vista general
        </button>
        <button
          type="button"
          onClick={onIrWall}
          className={`${chipBase} ${
            wallSel ? "border-emerald-400/50 bg-emerald-400/10 text-emerald-200" : chipOff
          }`}
        >
          Wall
        </button>
        {datos.departamentos.map((d: DeptoOficina) => (
          <button
            key={d.id}
            type="button"
            onClick={() => onIrDepto(d.id)}
            className={`${chipBase} ${deptoSel === d.id ? "text-zinc-100" : chipOff}`}
            style={
              deptoSel === d.id
                ? { borderColor: `${d.color}88`, background: `${d.color}1f` }
                : undefined
            }
          >
            {d.nombre}
          </button>
        ))}
      </div>
    </div>
  );
}
