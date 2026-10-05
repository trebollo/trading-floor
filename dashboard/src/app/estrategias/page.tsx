import { getStrategies } from "@/lib/data";
import { ESTADO_ESTILO, relativo } from "@/lib/format";
import { PageHeader, Panel } from "@/components/ui";
import { StrategyActions } from "@/components/StrategyActions";

export const revalidate = 20;

export default async function EstrategiasPage() {
  const { datos: estrategias, fuente } = await getStrategies();
  const vivas = estrategias.filter((e) => e.status === "VIVA").length;

  return (
    <>
      <PageHeader
        titulo="Estrategias"
        descripcion={`Ciclo de vida completo del catálogo. ${vivas} vivas de ${estrategias.length}. Los cambios de estado requieren doble confirmación y quedan en la memoria colectiva.`}
        fuente={fuente}
      />
      <Panel>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-borde)] text-left text-xs text-zinc-500">
                <th className="pb-2 pr-4 font-medium">Estrategia</th>
                <th className="pb-2 pr-4 font-medium">Estado</th>
                <th className="pb-2 pr-4 font-medium">Instrumentos</th>
                <th className="pb-2 pr-4 text-right font-medium">Sharpe</th>
                <th className="pb-2 pr-4 text-right font-medium">Max DD</th>
                <th className="pb-2 pr-4 font-medium">Actualizada</th>
                <th className="pb-2 text-right font-medium">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {estrategias.map((e) => {
                const estilo = ESTADO_ESTILO[e.status];
                return (
                  <tr key={e.id} className="border-b border-[var(--color-borde)]/50 last:border-0">
                    <td className="py-2.5 pr-4">
                      <p className="font-medium text-zinc-200">{e.nombre}</p>
                      <p className="text-[11px] text-zinc-600">{e.ownerAgent}</p>
                    </td>
                    <td className="py-2.5 pr-4">
                      <span className={`rounded-full border px-2 py-0.5 text-[11px] ${estilo.clase}`}>
                        {estilo.etiqueta}
                      </span>
                    </td>
                    <td className="py-2.5 pr-4 text-zinc-400">{e.instrumentos.join(", ") || "—"}</td>
                    <td className="py-2.5 pr-4 text-right tabular-nums text-zinc-300">
                      {e.sharpe?.toFixed(2) ?? "—"}
                    </td>
                    <td
                      className={`py-2.5 pr-4 text-right tabular-nums ${
                        e.maxDd !== null && e.maxDd < -15 ? "text-rose-300" : "text-zinc-300"
                      }`}
                    >
                      {e.maxDd !== null ? `${e.maxDd.toFixed(1)} %` : "—"}
                    </td>
                    <td className="py-2.5 pr-4 text-zinc-500">{relativo(e.actualizado)}</td>
                    <td className="py-2.5">
                      <StrategyActions id={e.id} status={e.status} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
