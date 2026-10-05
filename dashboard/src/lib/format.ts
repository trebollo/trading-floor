import type { StrategyStatus } from "./types";

const intl = new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const eur = (v: number) => `${intl.format(v)} €`;

export const pct = (v: number) => `${intl.format(v)} %`;

export const fecha = (iso: string) =>
  new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Madrid" }).format(
    new Date(iso),
  );

export const relativo = (iso: string) => {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "hace un momento";
  if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
  if (s < 86400) return `hace ${Math.floor(s / 3600)} h`;
  return `hace ${Math.floor(s / 86400)} d`;
};

/** Etiqueta y color por estado del ciclo de vida (migrations/0001_init.sql). */
export const ESTADO_ESTILO: Record<StrategyStatus, { etiqueta: string; clase: string }> = {
  PROPUESTA: { etiqueta: "Propuesta", clase: "bg-sky-500/15 text-sky-300 border-sky-500/30" },
  EN_BACKTEST: { etiqueta: "En backtest", clase: "bg-indigo-500/15 text-indigo-300 border-indigo-500/30" },
  VALIDADA: { etiqueta: "Validada", clase: "bg-violet-500/15 text-violet-300 border-violet-500/30" },
  APROBADA: { etiqueta: "Aprobada", clase: "bg-cyan-500/15 text-cyan-300 border-cyan-500/30" },
  PAPEL: { etiqueta: "En papel", clase: "bg-amber-500/15 text-amber-300 border-amber-500/30" },
  VIVA: { etiqueta: "Viva", clase: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30" },
  RETIRADA: { etiqueta: "Retirada", clase: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30" },
  BLOQUEADA: { etiqueta: "Bloqueada", clase: "bg-rose-500/15 text-rose-300 border-rose-500/30" },
};
