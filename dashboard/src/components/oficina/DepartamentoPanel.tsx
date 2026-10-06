"use client";

import Link from "next/link";
import { DoubleConfirm } from "@/components/DoubleConfirm";
import { cambiarEstadoEstrategia } from "@/app/actions";
import { ESTADO_ESTILO, relativo } from "@/lib/format";
import type { AgenteOficina, DeptoOficina } from "@/lib/oficina";

const ESTADO_PUNTO = {
  operativo: "bg-emerald-400",
  ocupado: "bg-sky-400",
  degradado: "bg-amber-400",
  pausado: "bg-zinc-500",
} as const;

const ESTADO_AGENTE = {
  trabajando: { texto: "trabajando", clase: "text-sky-300" },
  activo: { texto: "activo", clase: "text-emerald-300" },
  alerta: { texto: "alerta", clase: "text-rose-300" },
} as const;

export function DepartamentoPanel({ depto, onCerrar }: { depto: DeptoOficina; onCerrar: () => void }) {
  return (
    <aside
      className="absolute right-0 top-0 z-10 flex h-full w-full max-w-sm flex-col border-l border-[var(--color-borde)] bg-[var(--color-lienzo)]/94 backdrop-blur-xl"
      style={{ borderRight: `2px solid ${depto.color}66` }}
    >
      <header className="flex items-start gap-3 border-b border-[var(--color-borde)] p-4">
        <span
          className="mt-1 inline-block h-3 w-3 rounded-full"
          style={{ background: depto.color, boxShadow: `0 0 12px ${depto.color}88` }}
        />
        <div className="flex-1">
          <h2 className="text-base font-semibold">{depto.nombre}</h2>
          <p className="text-xs text-zinc-500">{depto.descripcion}</p>
        </div>
        <button
          type="button"
          onClick={onCerrar}
          className="rounded-lg border border-[var(--color-borde)] px-2 py-1 text-xs text-zinc-400 hover:bg-white/5"
        >
          ✕
        </button>
      </header>

      <div className="flex-1 space-y-5 overflow-y-auto p-4">
        {/* Estado del departamento */}
        <section>
          <div className="flex items-center gap-2 text-sm">
            <span className={`h-2 w-2 rounded-full ${ESTADO_PUNTO[depto.estado]}`} />
            <span className="capitalize text-zinc-200">{depto.estado}</span>
            <span className="text-xs text-zinc-500">· {depto.detalle}</span>
          </div>
        </section>

        {/* Plantilla */}
        <section>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
            Plantilla ({depto.agentes.length})
          </h3>
          <ul className="space-y-2">
            {depto.agentes.map((a) => {
              const est = ESTADO_AGENTE[a.estado];
              return (
                <li key={a.id} className="rounded-lg border border-[var(--color-borde)] p-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-zinc-200">{a.rol}</span>
                    <span className={`ml-auto text-[11px] ${est.clase}`}>● {est.texto}</span>
                  </div>
                  <p className="mt-0.5 font-mono text-[11px] text-zinc-600">{a.nombre}</p>
                  <p className="mt-1 text-xs text-zinc-400">{a.tarea}</p>
                </li>
              );
            })}
          </ul>
        </section>

        {/* Estrategias en las que trabaja */}
        <section>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
            Estrategias del departamento
          </h3>
          {depto.estrategias.length === 0 ? (
            <p className="text-xs text-zinc-600">
              Sin estrategias asignadas como propietario. Consulta el{" "}
              <Link href="/pipeline" className="text-emerald-300 hover:underline">
                pipeline completo
              </Link>
              .
            </p>
          ) : (
            <ul className="space-y-2">
              {depto.estrategias.map((s) => {
                const estilo = ESTADO_ESTILO[s.status];
                return (
                  <li key={s.id} className="rounded-lg border border-[var(--color-borde)] p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-zinc-200">{s.nombre}</span>
                      <span className={`rounded-full border px-2 py-0.5 text-[10px] ${estilo.clase}`}>
                        {estilo.etiqueta}
                      </span>
                      <span className="ml-auto text-[11px] text-zinc-600">{relativo(s.actualizado)}</span>
                    </div>
                    <div className="mt-1 flex items-center gap-3 text-[11px] text-zinc-500">
                      {s.sharpe !== null && <span>Sharpe {s.sharpe.toFixed(2)}</span>}
                      {s.maxDd !== null && <span>Max DD {s.maxDd.toFixed(1)} %</span>}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {s.status === "VIVA" && (
                        <>
                          <DoubleConfirm
                            etiqueta="Pausar"
                            etiquetaConfirm="¿Confirmar pausa?"
                            onConfirm={() => cambiarEstadoEstrategia(s.id, "pausar")}
                          />
                          <DoubleConfirm
                            etiqueta="Retirar"
                            etiquetaConfirm="¿Confirmar retiro?"
                            peligroso
                            onConfirm={() => cambiarEstadoEstrategia(s.id, "retirar")}
                          />
                        </>
                      )}
                      {s.status === "PAPEL" && (
                        <>
                          <DoubleConfirm
                            etiqueta="Activar"
                            etiquetaConfirm="¿Confirmar activación?"
                            onConfirm={() => cambiarEstadoEstrategia(s.id, "reactivar")}
                          />
                          <DoubleConfirm
                            etiqueta="Retirar"
                            etiquetaConfirm="¿Confirmar retiro?"
                            peligroso
                            onConfirm={() => cambiarEstadoEstrategia(s.id, "retirar")}
                          />
                        </>
                      )}
                      {s.status === "BLOQUEADA" && (
                        <DoubleConfirm
                          etiqueta="Desbloquear"
                          etiquetaConfirm="¿Devolver a papel?"
                          onConfirm={() => cambiarEstadoEstrategia(s.id, "desbloquear")}
                        />
                      )}
                      {s.status === "RETIRADA" && (
                        <DoubleConfirm
                          etiqueta="Reproponer"
                          etiquetaConfirm="¿Reiniciar el ciclo?"
                          onConfirm={() => cambiarEstadoEstrategia(s.id, "reproponer")}
                        />
                      )}
                      {(s.status === "PROPUESTA" || s.status === "EN_BACKTEST" || s.status === "VALIDADA" || s.status === "APROBADA") && (
                        <DoubleConfirm
                          etiqueta="Bloquear"
                          etiquetaConfirm="¿Confirmar bloqueo?"
                          peligroso
                          onConfirm={() => cambiarEstadoEstrategia(s.id, "bloquear")}
                        />
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* Acceso directo a ajustes globales */}
        {depto.id === "direccion" && (
          <p className="text-xs text-zinc-500">
            Las directrices y presupuestos se gestionan en la{" "}
            <Link href="/directivas" className="text-emerald-300 hover:underline">
              consola de directrices
            </Link>
            .
          </p>
        )}
      </div>
    </aside>
  );
}
