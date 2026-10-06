"use client";

// Curva de equity + drawdown. Base para los gráficos avanzados futuros
// (velas de market_data, distribución Monte Carlo, etc.) reutilizando Recharts.

import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EquityPoint } from "@/lib/types";

interface PayloadPunto {
  equity?: number;
  drawdownPct?: number;
  ts?: string;
}

function fmtEur(v: number): string {
  return `${Math.round(v).toLocaleString("es-ES")} €`;
}

function fmtFecha(ts: string): string {
  return new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short" }).format(new Date(ts));
}

function TooltipEquity({ active, payload, label }: {
  active?: boolean;
  payload?: Array<{ payload: PayloadPunto }>;
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const equity = Number(p.equity ?? 0);
  const dd = Number(p.drawdownPct ?? 0);
  return (
    <div className="rounded-lg border border-[var(--color-borde)] bg-[#0c1322]/95 px-3 py-2 shadow-xl backdrop-blur">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">
        {new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Madrid" }).format(
          new Date(String(label ?? p.ts ?? "")),
        )}
      </p>
      <p className="mt-1 text-sm font-semibold tabular-nums text-emerald-300">{fmtEur(equity)}</p>
      <p className="text-[11px] tabular-nums text-rose-300/90">DD {dd.toFixed(2)} %</p>
    </div>
  );
}

export function EquityChart({ puntos, altura = 280 }: { puntos: EquityPoint[]; altura?: number }) {
  if (puntos.length === 0) {
    return (
      <p className="flex h-40 items-center justify-center px-4 text-center text-sm text-zinc-600">
        Sin serie de P&amp;L disponible en la memoria colectiva todavía (fase 4: telemetría).
      </p>
    );
  }

  const datos = puntos.map((p) => ({
    ts: p.ts,
    equity: p.equity,
    // Drawdown en valor negativo para el área inferior
    drawdown: p.drawdownPct,
  }));

  return (
    <ResponsiveContainer width="100%" height={altura}>
      <AreaChart data={datos} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
        <defs>
          <linearGradient id="grad-equity" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#34d399" stopOpacity={0.4} />
            <stop offset="55%" stopColor="#34d399" stopOpacity={0.12} />
            <stop offset="100%" stopColor="#34d399" stopOpacity={0.02} />
          </linearGradient>
          <linearGradient id="grad-dd" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#fb7185" stopOpacity={0.05} />
            <stop offset="100%" stopColor="#fb7185" stopOpacity={0.32} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#1b2740" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="ts"
          tick={{ fill: "#64748b", fontSize: 11 }}
          tickFormatter={fmtFecha}
          minTickGap={48}
          stroke="#1b2740"
        />
        <YAxis
          yAxisId="eq"
          tick={{ fill: "#64748b", fontSize: 11 }}
          tickFormatter={(v: number) => `${Math.round(v).toLocaleString("es-ES")}`}
          tickCount={4}
          domain={["auto", "auto"]}
          width={64}
          stroke="#1b2740"
        />
        <YAxis
          yAxisId="dd"
          orientation="right"
          tick={{ fill: "#9f1239", fontSize: 10 }}
          tickFormatter={(v: number) => `${v.toFixed(1)}%`}
          tickCount={3}
          domain={["dataMin", 0]}
          width={46}
          stroke="transparent"
        />
        <Tooltip content={<TooltipEquity />} cursor={{ stroke: "#34d399", strokeWidth: 1, strokeDasharray: "4 4" }} />
        <ReferenceLine yAxisId="eq" y={puntos[0].equity} stroke="#334155" strokeDasharray="4 4" />
        {/* Capa de drawdown anclada abajo */}
        <Area
          yAxisId="dd"
          type="monotone"
          dataKey="drawdown"
          stroke="#fb7185"
          strokeWidth={1}
          fill="url(#grad-dd)"
          isAnimationActive={false}
          dot={false}
        />
        <Area
          yAxisId="eq"
          type="monotone"
          dataKey="equity"
          stroke="#34d399"
          strokeWidth={2}
          fill="url(#grad-equity)"
          isAnimationActive={false}
          dot={false}
          activeDot={{ r: 4, strokeWidth: 0, fill: "#34d399" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
