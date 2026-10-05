"use client";

import type { AgenteOficina, DeptoOficina } from "@/lib/oficina";

const ESTADO_AGENTE = {
  trabajando: { texto: "trabajando", clase: "border-sky-500/40 bg-sky-500/10 text-sky-300" },
  activo: { texto: "activo", clase: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" },
  alerta: { texto: "alerta", clase: "border-rose-500/40 bg-rose-500/10 text-rose-300" },
} as const;

export function AgentCard({
  agente,
  departamento,
  onCerrar,
}: {
  agente: AgenteOficina;
  departamento: DeptoOficina | null;
  onCerrar: () => void;
}) {
  const est = ESTADO_AGENTE[agente.estado];
  return (
    <div className="absolute bottom-4 left-4 z-10 w-80 rounded-xl border border-[var(--color-borde)] bg-[var(--color-lienzo)]/95 p-4 shadow-xl backdrop-blur">
      <div className="flex items-start gap-3">
        <span
          className="mt-0.5 inline-flex h-9 w-9 items-center justify-center rounded-full text-sm font-bold text-black"
          style={{ background: departamento?.color ?? "#64748b" }}
        >
          {agente.rol.slice(0, 1)}
        </span>
        <div className="flex-1">
          <p className="text-sm font-semibold text-zinc-100">{agente.rol}</p>
          <p className="font-mono text-[11px] text-zinc-600">{agente.nombre}</p>
        </div>
        <button
          type="button"
          onClick={onCerrar}
          className="rounded-lg border border-[var(--color-borde)] px-2 py-0.5 text-xs text-zinc-400 hover:bg-white/5"
        >
          ✕
        </button>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <span className={`rounded-full border px-2 py-0.5 text-[11px] ${est.clase}`}>{est.texto}</span>
      </div>
      <p className="mt-2 text-sm text-zinc-300">{agente.tarea}</p>
      {departamento && (
        <p className="mt-2 text-[11px] text-zinc-600">
          {departamento.nombre} · {departamento.detalle}
        </p>
      )}
    </div>
  );
}
