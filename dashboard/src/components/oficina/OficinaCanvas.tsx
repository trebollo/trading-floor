"use client";

import { useEffect, useRef, useState } from "react";
import { OficinaRenderer } from "./Renderer";
import { avanzarOficina } from "@/lib/oficina";
import type { AgenteOficina, OficinaData } from "@/lib/oficina";
import { DepartamentoPanel } from "./DepartamentoPanel";
import { AgentCard } from "./AgentCard";
import { WallPanel } from "./WallPanel";

const NIVEL_COLOR = { info: "#34d399", aviso: "#fbbf24", critico: "#f87171" } as const;

export function OficinaCanvas({ datos: datosIniciales }: { datos: OficinaData }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderRef = useRef<OficinaRenderer | null>(null);
  const [datos, setDatos] = useState(datosIniciales);
  const [deptoSel, setDeptoSel] = useState<string | null>(null);
  const [agenteSel, setAgenteSel] = useState<AgenteOficina | null>(null);
  const [wallSel, setWallSel] = useState(false);
  const [feedAbierto, setFeedAbierto] = useState(false);
  const [listo, setListo] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const renderer = new OficinaRenderer(canvas, datosIniciales, {
      onDepto: (id) => setDeptoSel(id),
      onAgente: (a) => setAgenteSel(a),
      onWall: (sel) => setWallSel(sel),
    });
    renderRef.current = renderer;
    setListo(true);

    const resizeReal = () => {
      const r = canvas.getBoundingClientRect();
      renderer.redimensionar(r.width, r.height, window.devicePixelRatio || 1);
    };
    resizeReal();
    window.addEventListener("resize", resizeReal);
    const ro = new ResizeObserver(resizeReal);
    ro.observe(canvas);

    return () => {
      window.removeEventListener("resize", resizeReal);
      ro.disconnect();
      renderer.destruir();
      renderRef.current = null;
    };
    // El renderer se monta una sola vez; los datos entran vía actualizarDatos.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // La escena siempre dibuja los últimos datos sin perder cámara ni selección.
  useEffect(() => {
    renderRef.current?.actualizarDatos(datos);
  }, [datos]);

  // En modo live, las nuevas instantáneas del servidor (revalidación ISR o
  // router.refresh) se adoptan tal cual; la simulación solo corre en demo, así
  // que no hay estado local que preservar.
  useEffect(() => {
    if (datosIniciales.fuente === "live") setDatos(datosIniciales);
  }, [datosIniciales]);

  // Simulación en vivo (solo demo): la oficina respira mientras se depura la UI.
  useEffect(() => {
    if (datosIniciales.fuente !== "demo") return;
    const id = setInterval(() => {
      if (document.hidden) return;
      setDatos((prev) => avanzarOficina(prev));
    }, 2500);
    return () => clearInterval(id);
  }, [datosIniciales.fuente]);

  const depto = datos.departamentos.find((d) => d.id === deptoSel) ?? null;
  // El agente seleccionado sigue vivo tras los ticks de simulación.
  const agente = agenteSel
    ? (datos.departamentos.flatMap((d) => d.agentes).find((a) => a.id === agenteSel.id) ?? agenteSel)
    : null;

  const ultimoEvento = datos.eventos[datos.eventos.length - 1];
  const colorDeDepto = (id: string | null) =>
    id ? (datos.departamentos.find((d) => d.id === id)?.color ?? "#94a3b8") : "#94a3b8";

  const irADepto = (id: string | null) => {
    setAgenteSel(null);
    setWallSel(false);
    setDeptoSel(id);
    renderRef.current?.seleccionarDepto(id);
    if (id) renderRef.current?.enfocarDepto(id);
    else renderRef.current?.resetCamara();
  };

  const irAWall = () => {
    setAgenteSel(null);
    setDeptoSel(null);
    setWallSel(true);
    renderRef.current?.seleccionarDepto(null);
    renderRef.current?.enfocarWall();
  };

  const cerrarAgente = () => {
    setAgenteSel(null);
    renderRef.current?.seleccionarAgente(null);
  };

  return (
    <div className="relative h-[calc(100dvh-3.5rem)] w-full overflow-hidden">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full touch-none" />

      {/* HUD superior izquierdo: cómo se maneja */}
      <div className="pointer-events-none absolute left-4 top-4 rounded-lg border border-[var(--color-borde)] bg-black/50 px-3 py-2 text-[11px] text-zinc-400 backdrop-blur">
        <p><span className="text-zinc-200">Arrastra</span> para mover · <span className="text-zinc-200">rueda</span> para zoom</p>
        <p><span className="text-zinc-200">Clic en una sala</span> para entrar · <span className="text-zinc-200">clic en la Wall</span> para la memoria operativa</p>
      </div>

      {/* Accesos rápidos (bajo el HUD, fuera del alcance de los paneles) */}
      {listo && (
        <div className="absolute left-4 top-24 z-10 flex max-w-[290px] flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => irADepto(null)}
            className={`rounded-lg border px-2.5 py-1 text-[11px] backdrop-blur ${
              !deptoSel && !wallSel
                ? "border-emerald-400/50 bg-emerald-400/10 text-emerald-200"
                : "border-[var(--color-borde)] bg-black/60 text-zinc-300 hover:bg-black/80"
            }`}
          >
            Vista general
          </button>
          <button
            type="button"
            onClick={irAWall}
            className={`rounded-lg border px-2.5 py-1 text-[11px] backdrop-blur ${
              wallSel
                ? "border-emerald-400/50 bg-emerald-400/10 text-emerald-200"
                : "border-[var(--color-borde)] bg-black/60 text-zinc-300 hover:bg-black/80"
            }`}
          >
            Wall
          </button>
          {datos.departamentos.map((d) => (
            <button
              key={d.id}
              type="button"
              onClick={() => irADepto(d.id)}
              className={`rounded-lg border px-2.5 py-1 text-[11px] backdrop-blur ${
                deptoSel === d.id ? "text-zinc-100" : "border-[var(--color-borde)] bg-black/60 text-zinc-300 hover:bg-black/80"
              }`}
              style={deptoSel === d.id ? { borderColor: `${d.color}88`, background: `${d.color}1f` } : undefined}
            >
              {d.nombre}
            </button>
          ))}
        </div>
      )}

      {/* Ticker de eventos */}
      {ultimoEvento && (
        <div className="absolute bottom-4 left-1/2 z-10 w-full max-w-xl -translate-x-1/2">
          {feedAbierto && (
            <div className="mb-2 max-h-72 space-y-1 overflow-y-auto rounded-xl border border-[var(--color-borde)] bg-black/80 p-3 backdrop-blur">
              {[...datos.eventos].reverse().map((e) => (
                <div key={e.id} className="flex items-start gap-2 text-[11px]">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: NIVEL_COLOR[e.nivel] }} />
                  <span className="shrink-0 font-mono text-zinc-600">
                    {new Date(e.ts).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Madrid" })}
                  </span>
                  <span className="shrink-0 font-medium" style={{ color: colorDeDepto(e.departamento) }}>
                    {e.departamento
                      ? (datos.departamentos.find((d) => d.id === e.departamento)?.nombre ?? e.departamento)
                      : "Sistema"}
                  </span>
                  <span className="text-zinc-300">{e.texto}</span>
                </div>
              ))}
            </div>
          )}
          <button
            type="button"
            onClick={() => setFeedAbierto((v) => !v)}
            className="flex w-full items-center gap-2 rounded-lg border border-[var(--color-borde)] bg-black/70 px-3 py-2 text-left text-xs backdrop-blur hover:bg-black/80"
          >
            <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full" style={{ background: NIVEL_COLOR[ultimoEvento.nivel] }} />
            <span className="shrink-0 font-medium" style={{ color: colorDeDepto(ultimoEvento.departamento) }}>
              {ultimoEvento.departamento
                ? (datos.departamentos.find((d) => d.id === ultimoEvento.departamento)?.nombre ?? ultimoEvento.departamento)
                : "Sistema"}
            </span>
            <span key={ultimoEvento.id} className="flex-1 truncate text-zinc-300">{ultimoEvento.texto}</span>
            {/* Hora fija con zona explícita: determinista entre servidor y cliente (sin hydration mismatch). */}
            <span className="shrink-0 text-[10px] text-zinc-600">
              {new Date(ultimoEvento.ts).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid" })}
            </span>
            <span className="shrink-0 text-[10px] text-zinc-600">{feedAbierto ? "▾" : "▴"}</span>
          </button>
        </div>
      )}

      {/* Ficha del agente */}
      {agente && (
        <AgentCard
          agente={agente}
          departamento={datos.departamentos.find((d) => d.id === agente.departamento) ?? null}
          onCerrar={cerrarAgente}
        />
      )}

      {/* Panel de la Wall (memoria operativa) */}
      {wallSel && !agente && (
        <WallPanel datos={datos} onCerrar={() => setWallSel(false)} />
      )}

      {/* Panel del departamento */}
      {depto && !agente && !wallSel && (
        <DepartamentoPanel
          key={depto.id}
          depto={depto}
          onCerrar={() => {
            setDeptoSel(null);
            renderRef.current?.seleccionarDepto(null);
          }}
        />
      )}
    </div>
  );
}
