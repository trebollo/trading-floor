import { getDirectives } from "@/lib/data";
import { fecha } from "@/lib/format";
import { PageHeader, Panel } from "@/components/ui";
import { DirectiveForm } from "@/components/DirectiveForm";
import { RevocarDirectiva } from "@/components/RevocarDirectiva";

export const revalidate = 20;

export default async function DirectivasPage() {
  const { datos: directrices, fuente } = await getDirectives();

  return (
    <>
      <PageHeader
        titulo="Directrices del CEO"
        descripcion="Único canal de gobierno del sistema. Cada directriz queda registrada en la memoria colectiva y alimenta al siguiente ciclo de investigación."
        fuente={fuente}
      />

      <Panel titulo="Nueva directriz">
        <DirectiveForm />
      </Panel>

      <div className="mt-6">
        <Panel titulo={`Historial (${directrices.length})`}>
          <ul className="space-y-3">
            {directrices.map((d) => {
              const vigente = d.status === "VIGENTE";
              return (
                <li
                  key={d.id}
                  className={`rounded-lg border p-4 ${
                    vigente ? "border-[var(--color-borde)]" : "border-[var(--color-borde)]/50 opacity-60"
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[11px] ${
                        vigente
                          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                          : "border-zinc-500/30 bg-zinc-500/10 text-zinc-400"
                      }`}
                    >
                      {d.status}
                    </span>
                    <span className="rounded-full border border-[var(--color-borde)] px-2 py-0.5 text-[11px] text-zinc-400">
                      {d.scope}
                    </span>
                    <span className="text-[11px] text-zinc-600">
                      {fecha(d.efectiva)} · {d.ceoId}
                    </span>
                    {vigente && (
                      <span className="ml-auto">
                        <RevocarDirectiva id={d.id} />
                      </span>
                    )}
                  </div>
                  <p className="mt-2 text-sm text-zinc-300">{d.texto}</p>
                </li>
              );
            })}
            {directrices.length === 0 && (
              <li className="text-sm text-zinc-600">Sin directrices registradas todavía.</li>
            )}
          </ul>
        </Panel>
      </div>
    </>
  );
}
