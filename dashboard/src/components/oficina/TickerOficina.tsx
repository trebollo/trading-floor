"use client";

// Ticker inferior de la oficina: tabla de eventos filtrable por departamento.

import type { EventoOficina, OficinaData } from "@/lib/oficina";
import { useState } from "react";

const NIVEL_COLOR: Record<EventoOficina["nivel"], string> = {
  info: "text-emerald-400",
  aviso: "text-amber-400",
  critico: "text-rose-400",
};

const NIVEL_PUNTO: Record<EventoOficina["nivel"], string> = {
  info: "bg-emerald-400",
  aviso: "bg-amber-400",
  critico: "bg-rose-400",
};

function hora(iso: string): string {
  return new Date(iso).toLocaleTimeString("es-ES", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "Europe/Madrid",
  });
}

export function TickerOficina({ datos }: { datos: OficinaData }) {
  const [filtro, setFiltro] = useState<string>("todos");
  const [abierto, setAbierto] = useState(true);

  const deptos = datos.departamentos;
  const eventos = [...datos.eventos].reverse();
  const filtrados = filtro === "todos" ? eventos : eventos.filter((e) => e.departamento === filtro);
  const ultimo = datos.eventos[datos.eventos.length - 1];

  const nombreDe = (id: string | null) =>
    id ? (deptos.find((d) => d.id === id)?.nombre ?? id) : "Sistema";

  const colorDe = (id: string | null) =>
    id ? (deptos.find((d) => d.id === id)?.color ?? "#94a3b8") : "#94a3b8";

  return (
    <div className="absolute bottom-0 left-0 right-0 z-10 px-4 pb-4">
      <div className="mx-auto max-w-5xl overflow-hidden rounded-xl border border-[var(--color-borde)] bg-black/75 backdrop-blur-md">
        {/* Filtros */}
        <div className="flex items-center gap-1.5 overflow-x-auto border-b border-[var(--color-borde)] px-3 py-2">
          <span className="shrink-0 text-[10px] font-medium uppercase tracking-wider text-zinc-500">
            Filtros
          </span>
          <button
            type="button"
            onClick={() => setFiltro("todos")}
            className={`shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] ${
              filtro === "todos"
                ? "border-emerald-400/50 bg-emerald-400/10 text-emerald-200"
                : "border-[var(--color-borde)] bg-black/40 text-zinc-400 hover:bg-black/60"
            }`}
          >
            Todos
          </button>
          {deptos.map((d) => (
            <button
              key={d.id}
              type="button"
              onClick={() => setFiltro(d.id)}
              className="shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] transition-colors"
              style={
                filtro === d.id
                  ? { borderColor: `${d.color}88`, background: `${d.color}22`, color: d.color }
                  : { borderColor: "var(--color-borde)", background: "rgba(0,0,0,0.4)", color: "#a1a1aa" }
              }
            >
              {d.nombre}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setAbierto((v) => !v)}
            className="ml-auto shrink-0 rounded-lg border border-[var(--color-borde)] px-2 py-0.5 text-[11px] text-zinc-400 hover:bg-black/60"
          >
            {abierto ? "▾ Ocultar" : "▴ Mostrar"}
          </button>
        </div>

        {/* Último evento siempre visible */}
        {ultimo && (
          <div className="flex items-center gap-2 border-b border-[var(--color-borde)] px-3 py-2 text-xs">
            <span className={`h-1.5 w-1.5 shrink-0 animate-pulse rounded-full ${NIVEL_PUNTO[ultimo.nivel]}`} />
            <span className="shrink-0 font-medium" style={{ color: colorDe(ultimo.departamento) }}>
              {nombreDe(ultimo.departamento)}
            </span>
            <span className="flex-1 truncate text-zinc-300">{ultimo.texto}</span>
            <span className="shrink-0 font-mono text-[10px] text-zinc-600">{hora(ultimo.ts)}</span>
          </div>
        )}

        {/* Tabla de eventos */}
        {abierto && (
          <div className="max-h-56 overflow-y-auto">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-black/80 text-[10px] uppercase tracking-wider text-zinc-500">
                <tr>
                  <th className="px-3 py-2 font-medium">Hora</th>
                  <th className="px-3 py-2 font-medium">Sala</th>
                  <th className="px-3 py-2 font-medium">Nivel</th>
                  <th className="px-3 py-2 font-medium">Evento</th>
                </tr>
              </thead>
              <tbody>
                {filtrados.map((e) => (
                  <tr key={e.id} className="border-t border-[var(--color-borde)]/60 hover:bg-white/[0.03]">
                    <td className="whitespace-nowrap px-3 py-1.5 font-mono text-[11px] text-zinc-500">
                      {hora(e.ts)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-1.5 font-medium" style={{ color: colorDe(e.departamento) }}>
                      {nombreDe(e.departamento)}
                    </td>
                    <td className={`px-3 py-1.5 ${NIVEL_COLOR[e.nivel]}`}>{e.nivel}</td>
                    <td className="px-3 py-1.5 text-zinc-300">{e.texto}</td>
                  </tr>
                ))}
                {filtrados.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-4 text-center text-zinc-600">
                      Sin eventos para este filtro.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
