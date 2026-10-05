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

export function EquityChart({ puntos, altura = 280 }: { puntos: EquityPoint[]; altura?: number }) {
  if (puntos.length === 0) {
    return (
      <p className="flex h-40 items-center justify-center text-sm text-zinc-600">
        Sin serie de P&amp;L disponible en la memoria colectiva todavía (fase 4: telemetría).
      </p>
    );
  }

  const fmt = (v: number) => `${Math.round(v).toLocaleString("es-ES")} €`;

  return (
    <ResponsiveContainer width="100%" height={altura}>
      <AreaChart data={puntos} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
        <defs>
          <linearGradient id="grad-equity" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#34d399" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#34d399" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#1b2740" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="ts"
          tick={{ fill: "#64748b", fontSize: 11 }}
          tickFormatter={(ts: string) =>
            new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short" }).format(new Date(ts))
          }
          minTickGap={48}
          stroke="#1b2740"
        />
        <YAxis
          tick={{ fill: "#64748b", fontSize: 11 }}
          tickFormatter={fmt}
          domain={["auto", "auto"]}
          width={72}
          stroke="#1b2740"
        />
        <Tooltip
          contentStyle={{
            background: "#0c1322",
            border: "1px solid #1b2740",
            borderRadius: 8,
            fontSize: 12,
          }}
          labelFormatter={(ts) =>
            new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short" }).format(new Date(String(ts)))
          }
          formatter={(value) => [fmt(Number(value)), "Equity"]}
        />
        <ReferenceLine y={puntos[0].equity} stroke="#334155" strokeDasharray="4 4" />
        <Area
          type="monotone"
          dataKey="equity"
          stroke="#34d399"
          strokeWidth={2}
          fill="url(#grad-equity)"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
