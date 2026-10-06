"use client";

// Tarjetas KPI de la memoria operativa con acento visual y micro-barras.

import type { EquityPoint, Kpis } from "@/lib/types";
import { eur, pct } from "@/lib/format";

function Anillo({ valor, color, etiqueta }: { valor: number; color: string; etiqueta: string }) {
  const v = Math.min(Math.max(valor, 0), 100);
  const r = 16;
  const c = 2 * Math.PI * r;
  const offset = c - (v / 100) * c;
  return (
    <div className="relative h-10 w-10 shrink-0" title={`${etiqueta}: ${valor.toFixed(0)} %`}>
      <svg viewBox="0 0 40 40" className="h-10 w-10 -rotate-90">
        <circle cx="20" cy="20" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="3" />
        <circle
          cx="20"
          cy="20"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-[9px] font-semibold tabular-nums text-zinc-300">
        {Math.round(v)}
      </span>
    </div>
  );
}

function Tarjeta({
  etiqueta,
  valor,
  detalle,
  tono = "neutral",
  barra,
  colorBarra,
}: {
  etiqueta: string;
  valor: string;
  detalle?: string;
  tono?: "neutral" | "positivo" | "negativo" | "aviso";
  barra?: number;
  colorBarra?: string;
}) {
  const tonos = {
    neutral: "text-zinc-100",
    positivo: "text-emerald-300",
    negativo: "text-rose-300",
    aviso: "text-amber-300",
  } as const;
  return (
    <div className="rounded-xl border border-[var(--color-borde)] bg-black/40 p-3 shadow-[0_1px_0_rgba(255,255,255,0.03)_inset]">
      <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">{etiqueta}</p>
      <p className={`mt-1 text-lg font-semibold tabular-nums ${tonos[tono]}`}>{valor}</p>
      {barra !== undefined && (
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/8">
          <div
            className="h-full rounded-full transition-[width] duration-500"
            style={{ width: `${Math.min(Math.max(barra, 0), 100)}%`, background: colorBarra ?? "#34d399" }}
          />
        </div>
      )}
      {detalle && <p className="mt-1 text-[11px] text-zinc-600">{detalle}</p>}
    </div>
  );
}

export function KpiWall({ kpis, equity }: { kpis: Kpis; equity: EquityPoint[] }) {
  const dd = equity.length > 0 ? equity[equity.length - 1].drawdownPct : 0;
  const ddAbs = Math.abs(dd);
  const ddTono = ddAbs > 12 ? "negativo" : ddAbs > 6 ? "aviso" : "neutral";
  const pnlHoyTono = kpis.pnlDia >= 0 ? "positivo" : "negativo";
  const pnlAcumTono = kpis.pnlAcumulado >= 0 ? "positivo" : "negativo";
  const expoTono = kpis.exposicionPct > 60 ? "aviso" : "neutral";
  const presupTono = kpis.presupuestoUsadoPct > 80 ? "aviso" : "neutral";

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <Tarjeta
          etiqueta="P&L hoy"
          valor={eur(kpis.pnlDia)}
          detalle="sesión en curso"
          tono={pnlHoyTono}
          barra={Math.min(Math.abs(kpis.pnlDia) / 5, 100)}
          colorBarra={kpis.pnlDia >= 0 ? "#34d399" : "#fb7185"}
        />
        <Tarjeta
          etiqueta="P&L acumulado"
          valor={eur(kpis.pnlAcumulado)}
          detalle="desde el origen"
          tono={pnlAcumTono}
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="flex items-center gap-3 rounded-xl border border-[var(--color-borde)] bg-black/40 p-3">
          <Anillo valor={kpis.exposicionPct} color={kpis.exposicionPct > 60 ? "#fbbf24" : "#34d399"} etiqueta="Exposición" />
          <div className="min-w-0">
            <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">Exposición</p>
            <p className={`text-lg font-semibold tabular-nums ${expoTono === "aviso" ? "text-amber-300" : "text-zinc-100"}`}>
              {pct(kpis.exposicionPct)}
            </p>
            <p className="text-[11px] text-zinc-600">sobre capital</p>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-xl border border-[var(--color-borde)] bg-black/40 p-3">
          <Anillo
            valor={kpis.presupuestoUsadoPct}
            color={kpis.presupuestoUsadoPct > 80 ? "#fbbf24" : "#38bdf8"}
            etiqueta="Presupuesto LLM"
          />
          <div className="min-w-0">
            <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">Presupuesto</p>
            <p className={`text-lg font-semibold tabular-nums ${presupTono === "aviso" ? "text-amber-300" : "text-zinc-100"}`}>
              {pct(kpis.presupuestoUsadoPct)}
            </p>
            <p className="text-[11px] text-zinc-600">ciclo mensual</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Tarjeta
          etiqueta="Estrategias vivas"
          valor={String(kpis.estrategiasVivas)}
          detalle={`modo ${kpis.modo}`}
        />
        <Tarjeta
          etiqueta="Drawdown"
          valor={pct(-ddAbs)}
          detalle="sobre la curva de equity"
          tono={ddTono}
          barra={Math.min(ddAbs * 4, 100)}
          colorBarra="#fb7185"
        />
      </div>
    </div>
  );
}
