import { getAudit } from "@/lib/data";
import { fecha } from "@/lib/format";
import { PageHeader, Panel } from "@/components/ui";

export const revalidate = 20;

export default async function AuditoriaPage() {
  const { datos: entradas, fuente } = await getAudit(100);

  return (
    <>
      <PageHeader
        titulo="Auditoría"
        descripcion="Log de eventos con hash encadenado: cualquier manipulación del histórico es detectable. Últimas 100 entradas, más recientes primero."
        fuente={fuente}
      />

      <Panel>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-borde)] text-left text-xs text-zinc-500">
                <th className="pb-2 pr-4 font-medium">Seq</th>
                <th className="pb-2 pr-4 font-medium">Momento</th>
                <th className="pb-2 pr-4 font-medium">Actor</th>
                <th className="pb-2 pr-4 font-medium">Evento</th>
                <th className="pb-2 pr-4 font-medium">Payload</th>
                <th className="pb-2 font-medium">Hash</th>
              </tr>
            </thead>
            <tbody className="font-mono text-xs">
              {entradas.map((e) => (
                <tr key={e.seq} className="border-b border-[var(--color-borde)]/40 last:border-0">
                  <td className="py-2 pr-4 tabular-nums text-zinc-500">{e.seq}</td>
                  <td className="py-2 pr-4 text-zinc-400">{fecha(e.ts)}</td>
                  <td className="py-2 pr-4 text-sky-300">{e.actor}</td>
                  <td className="py-2 pr-4 text-emerald-300">{e.eventType}</td>
                  <td className="max-w-xs truncate py-2 pr-4 text-zinc-500" title={e.payload}>
                    {e.payload}
                  </td>
                  <td className="py-2 text-zinc-600">{e.hash.slice(0, 12)}…</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
