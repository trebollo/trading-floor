"use client";

// Contenedor del piso de trading: escena Three.js + HUD + paneles + ticker.
// La escena se importa de forma dinámica (solo cliente) para no inflar el bundle SSR.

import { useEffect, useRef, useState } from "react";
import { avanzarOficina } from "@/lib/oficina";
import type { AgenteOficina, OficinaData } from "@/lib/oficina";
import { DepartamentoPanel } from "./DepartamentoPanel";
import { AgentCard } from "./AgentCard";
import { WallPanel } from "./WallPanel";
import { HudOficina } from "./HudOficina";
import { TickerOficina } from "./TickerOficina";

type EscenaModulo = typeof import("./EscenaOficina");
type EscenaInstancia = InstanceType<EscenaModulo["EscenaOficina"]>;

export function OficinaCanvas({ datos: datosIniciales }: { datos: OficinaData }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const escenaRef = useRef<EscenaInstancia | null>(null);
  const [datos, setDatos] = useState(datosIniciales);
  const [deptoSel, setDeptoSel] = useState<string | null>(null);
  const [agenteSel, setAgenteSel] = useState<AgenteOficina | null>(null);
  const [wallSel, setWallSel] = useState(false);
  const [listo, setListo] = useState(false);
  const [cargando, setCargando] = useState(true);
  const [errorEscena, setErrorEscena] = useState<string | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let cancelado = false;
    let limpieza: (() => void) | undefined;

    import("./EscenaOficina")
      .then(({ EscenaOficina }) => {
        if (cancelado || !canvasRef.current) return;
        const escena = new EscenaOficina(canvas, datosIniciales, {
          onDepto: (id) => setDeptoSel(id),
          onAgente: (a) => setAgenteSel(a),
          onWall: (sel) => setWallSel(sel),
        });
        escenaRef.current = escena;
        setListo(true);
        setCargando(false);

        const resizeReal = () => {
          const r = canvas.getBoundingClientRect();
          escena.redimensionar(r.width, r.height, window.devicePixelRatio || 1);
        };
        resizeReal();
        window.addEventListener("resize", resizeReal);
        const ro = new ResizeObserver(resizeReal);
        ro.observe(canvas);

        limpieza = () => {
          window.removeEventListener("resize", resizeReal);
          ro.disconnect();
          escena.destruir();
          escenaRef.current = null;
        };
      })
      .catch((err: unknown) => {
        if (cancelado) return;
        console.error("No se pudo montar la escena 3D:", err);
        setErrorEscena(err instanceof Error ? err.message : "Error desconocido al montar WebGL");
        setCargando(false);
      });

    return () => {
      cancelado = true;
      limpieza?.();
    };
    // El renderer se monta una sola vez; los datos entran vía actualizarDatos.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // La escena siempre dibuja los últimos datos sin perder cámara ni selección.
  useEffect(() => {
    escenaRef.current?.actualizarDatos(datos);
  }, [datos]);

  // En modo live, las instantáneas del servidor se adoptan tal cual.
  useEffect(() => {
    if (datosIniciales.fuente === "live") setDatos(datosIniciales);
  }, [datosIniciales]);

  // Simulación en vivo (solo demo).
  useEffect(() => {
    if (datosIniciales.fuente !== "demo") return;
    const id = setInterval(() => {
      if (document.hidden) return;
      setDatos((prev) => avanzarOficina(prev));
    }, 2500);
    return () => clearInterval(id);
  }, [datosIniciales.fuente]);

  const depto = datos.departamentos.find((d) => d.id === deptoSel) ?? null;
  const agente = agenteSel
    ? (datos.departamentos.flatMap((d) => d.agentes).find((a) => a.id === agenteSel.id) ?? agenteSel)
    : null;

  const irADepto = (id: string | null) => {
    setAgenteSel(null);
    setWallSel(false);
    setDeptoSel(id);
    escenaRef.current?.seleccionarDepto(id);
    if (id) escenaRef.current?.enfocarDepto(id);
    else escenaRef.current?.resetCamara();
  };

  const irAWall = () => {
    setAgenteSel(null);
    setDeptoSel(null);
    setWallSel(true);
    escenaRef.current?.seleccionarDepto(null);
    escenaRef.current?.enfocarWall();
  };

  const cerrarAgente = () => {
    setAgenteSel(null);
    escenaRef.current?.seleccionarAgente(null);
  };

  return (
    <div className="relative h-[calc(100dvh-3.5rem)] w-full overflow-hidden">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full touch-none" />

      {/* Viñeta / marco premium */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_80%_at_50%_0%,transparent_40%,rgba(3,6,12,0.45)_100%)]" />

      {cargando && (
        <div className="absolute inset-0 flex items-center justify-center bg-[var(--color-lienzo)]">
          <div className="text-center">
            <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-emerald-400/30 border-t-emerald-400" />
            <p className="mt-3 text-sm text-zinc-400">Montando la planta del trading floor…</p>
          </div>
        </div>
      )}

      {errorEscena && (
        <div className="absolute inset-x-0 top-1/3 z-10 mx-auto max-w-md rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-center backdrop-blur">
          <p className="text-sm font-medium text-amber-200">Escena 3D no disponible</p>
          <p className="mt-1 text-xs text-amber-100/70">{errorEscena}</p>
          <p className="mt-2 text-[11px] text-zinc-400">
            Los paneles, el ticker y la memoria operativa siguen operativos.
          </p>
        </div>
      )}

      {listo && (
        <HudOficina
          datos={datos}
          deptoSel={deptoSel}
          wallSel={wallSel}
          onIrGeneral={() => irADepto(null)}
          onIrWall={irAWall}
          onIrDepto={(id) => irADepto(id)}
        />
      )}

      <TickerOficina datos={datos} />

      {agente && (
        <AgentCard
          agente={agente}
          departamento={datos.departamentos.find((d) => d.id === agente.departamento) ?? null}
          onCerrar={cerrarAgente}
        />
      )}

      {wallSel && !agente && <WallPanel datos={datos} onCerrar={() => setWallSel(false)} />}

      {depto && !agente && !wallSel && (
        <DepartamentoPanel
          key={depto.id}
          depto={depto}
          onCerrar={() => {
            setDeptoSel(null);
            escenaRef.current?.seleccionarDepto(null);
          }}
        />
      )}
    </div>
  );
}
