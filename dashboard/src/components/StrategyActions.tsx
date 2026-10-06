"use client";

import { cambiarEstadoEstrategia } from "@/app/actions";
import { DoubleConfirm } from "@/components/DoubleConfirm";
import type { StrategyStatus } from "@/lib/types";

/** Acciones de ciclo de vida permitidas desde el dashboard, por estado actual. */
const ACCIONES: Record<StrategyStatus, { accion: "pausar" | "reactivar" | "desbloquear" | "reproponer" | "retirar" | "bloquear"; etiqueta: string; peligroso: boolean }[]> = {
  PROPUESTA: [],
  EN_BACKTEST: [{ accion: "bloquear", etiqueta: "Bloquear", peligroso: true }],
  VALIDADA: [{ accion: "bloquear", etiqueta: "Bloquear", peligroso: true }],
  APROBADA: [{ accion: "bloquear", etiqueta: "Bloquear", peligroso: true }],
  PAPEL: [
    { accion: "reactivar", etiqueta: "Activar", peligroso: false },
    { accion: "retirar", etiqueta: "Retirar", peligroso: true },
  ],
  VIVA: [
    { accion: "pausar", etiqueta: "Pausar", peligroso: false },
    { accion: "retirar", etiqueta: "Retirar", peligroso: true },
  ],
  RETIRADA: [{ accion: "reproponer", etiqueta: "Reproponer", peligroso: false }],
  BLOQUEADA: [{ accion: "desbloquear", etiqueta: "Desbloquear", peligroso: false }],
};

export function StrategyActions({ id, status }: { id: string; status: StrategyStatus }) {
  const acciones = ACCIONES[status];
  if (acciones.length === 0) return <span className="text-xs text-zinc-700">—</span>;
  return (
    <div className="flex justify-end gap-1.5">
      {acciones.map((a) => (
        <DoubleConfirm
          key={a.accion}
          etiqueta={a.etiqueta}
          etiquetaConfirm={`¿Confirmar ${a.etiqueta.toLowerCase()}?`}
          peligroso={a.peligroso}
          onConfirm={() => cambiarEstadoEstrategia(id, a.accion)}
        />
      ))}
    </div>
  );
}
