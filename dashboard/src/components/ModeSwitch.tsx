"use client";

// Cambio de modo del sistema (PAPER / LIVE_CAPITAL_REDUCIDO / LIVE).
// Exige doble confirmación porque altera el gradiente de exposición (P3).

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { cambiarModoSistema } from "@/app/actions";
import type { SystemMode } from "@/lib/types";

const MODOS: { valor: SystemMode; etiqueta: string; clase: string }[] = [
  { valor: "PAPER", etiqueta: "PAPER", clase: "data-[on=true]:bg-amber-500/20 data-[on=true]:text-amber-200 data-[on=true]:border-amber-500/40" },
  { valor: "LIVE_CAPITAL_REDUCIDO", etiqueta: "CAPITAL REDUCIDO", clase: "data-[on=true]:bg-sky-500/20 data-[on=true]:text-sky-200 data-[on=true]:border-sky-500/40" },
  { valor: "LIVE", etiqueta: "LIVE", clase: "data-[on=true]:bg-rose-500/20 data-[on=true]:text-rose-200 data-[on=true]:border-rose-500/40" },
];

export function ModeSwitch({ modoActual }: { modoActual: SystemMode }) {
  const [confirmar, setConfirmar] = useState<SystemMode | null>(null);
  const [pendiente, startTransition] = useTransition();
  const router = useRouter();

  const cambiar = (modo: SystemMode) => {
    setConfirmar(null);
    startTransition(async () => {
      await cambiarModoSistema(modo);
      router.refresh();
    });
  };

  return (
    <div className="flex items-center gap-2">
      {MODOS.map((m) => {
        const on = m.valor === modoActual;
        const armado = confirmar === m.valor;
        return armado ? (
          <span key={m.valor} className="inline-flex items-center gap-1">
            <button
              type="button"
              onClick={() => cambiar(m.valor)}
              disabled={pendiente}
              className="rounded-lg border border-amber-400 bg-amber-400/10 px-2.5 py-1 text-xs text-amber-200"
            >
              ¿Confirmar {m.etiqueta}?
            </button>
            <button
              type="button"
              onClick={() => setConfirmar(null)}
              className="rounded-lg border border-[var(--color-borde)] px-2 py-1 text-xs text-zinc-400"
            >
              ✕
            </button>
          </span>
        ) : (
          <button
            key={m.valor}
            type="button"
            data-on={on}
            onClick={() => (on ? undefined : setConfirmar(m.valor))}
            disabled={pendiente}
            className={`rounded-lg border px-2.5 py-1 text-xs transition-colors disabled:opacity-50 ${
              on ? m.clase : "border-[var(--color-borde)] text-zinc-500 hover:bg-white/5"
            }`}
          >
            {m.etiqueta}
          </button>
        );
      })}
    </div>
  );
}
