"use client";

import { useEffect, useRef, useState } from "react";
import { OficinaRenderer } from "./Renderer";
import type { AgenteOficina, OficinaData } from "@/lib/oficina";
import { DepartamentoPanel } from "./DepartamentoPanel";
import { AgentCard } from "./AgentCard";

export function OficinaCanvas({ datos }: { datos: OficinaData }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderRef = useRef<OficinaRenderer | null>(null);
  const [deptoSel, setDeptoSel] = useState<string | null>(null);
  const [agenteSel, setAgenteSel] = useState<AgenteOficina | null>(null);
  const [listo, setListo] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const renderer = new OficinaRenderer(canvas, datos, {
      onDepto: (id) => setDeptoSel(id),
      onAgente: (a) => setAgenteSel(a),
    });
    renderRef.current = renderer;
    setListo(true);

    const resize = () => {
      renderer.redimensionar(window.innerWidth, window.innerHeight, window.devicePixelRatio || 1);
    };
    // El canvas cubre el área bajo el header; dimensionar al viewport menos el header.
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
  }, [datos]);

  const depto = datos.departamentos.find((d) => d.id === deptoSel) ?? null;

  return (
    <div className="relative h-[calc(100dvh-3.5rem)] w-full overflow-hidden">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />

      {/* HUD superior izquierdo: cómo se maneja */}
      <div className="pointer-events-none absolute left-4 top-4 rounded-lg border border-[var(--color-borde)] bg-black/50 px-3 py-2 text-[11px] text-zinc-400 backdrop-blur">
        <p><span className="text-zinc-200">Arrastra</span> para mover · <span className="text-zinc-200">rueda</span> para zoom</p>
        <p><span className="text-zinc-200">Clic en una sala</span> para entrar · <span className="text-zinc-200">clic en un agente</span> para ver su tarea</p>
      </div>

      {/* Botón de reencuadre */}
      {listo && (
        <button
          type="button"
          onClick={() => renderRef.current?.resetCamara()}
          className="absolute bottom-4 right-4 rounded-lg border border-[var(--color-borde)] bg-black/60 px-3 py-1.5 text-xs text-zinc-300 backdrop-blur hover:bg-black/80"
        >
          Vista general
        </button>
      )}

      {/* Ficha del agente */}
      {agenteSel && (
        <AgentCard
          agente={agenteSel}
          departamento={datos.departamentos.find((d) => d.id === agenteSel.departamento) ?? null}
          onCerrar={() => {
            setAgenteSel(null);
            renderRef.current?.seleccionarAgente(null);
          }}
        />
      )}

      {/* Panel del departamento */}
      {depto && !agenteSel && (
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
