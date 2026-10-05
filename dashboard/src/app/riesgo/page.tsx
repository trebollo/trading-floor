import { getRiskChecks } from "@/lib/data";
import { relativo } from "@/lib/format";
import { PageHeader, Panel, StatCard } from "@/components/ui";

export const revalidate = 20;

// Espejo de config/guardrails.yaml para vista de solo lectura.
// En serverless el YAML no está disponible en runtime; estos valores se
// sincronizan manualmente hasta que exista una API de configuración (fase 4).
const LIMITES = [
  { nombre: "Riesgo máximo por operación", valor: "1,0 % capital" },
  { nombre: "Exposición bruta máxima", valor: "60 % (directriz CEO)" },
  { nombre: "Drawdown → modo solo-cierre", valor: "-10 %" },
  { nombre: "Techo de gasto del sistema", valor: "5 €/día (G3)" },
  { nombre: "Llamadas LLM por agente", valor: "60/hora" },
];

export default async function RiesgoPage() {
  const { datos: checks, fuente } = await getRiskChecks();
  const vetos = checks.filter((c) => c.verdict === "RECHAZADA").length;
  const aprobadas = checks.length - vetos;

  return (
    <>
      <PageHeader
        titulo="Riesgo"
        descripcion="Gate pre-trade determinista fail-closed. El veto del Risk Dept no puede ser anulado desde el dashboard, solo revocado por el CEO (P2)."
        fuente={fuente}
      />

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard etiqueta="Chequeos (ventana)" valor={String(checks.length)} />
        <StatCard etiqueta="Vetos" valor={String(vetos)} tono={vetos > 0 ? "negativo" : "neutral"} />
        <StatCard etiqueta="Aprobadas" valor={String(aprobadas)} tono="positivo" />
        <StatCard etiqueta="Modo del gate" valor="Fail-closed" detalle="Sin token válido, no hay orden" />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Panel titulo="Chequeos recientes" className="xl:col-span-2">
          <ul className="divide-y divide-[var(--color-borde)]/50">
            {checks.map((c) => (
              <li key={c.id} className="py-2.5">
                <div className="flex items-center gap-3 text-sm">
                  <span
                    className={`w-20 shrink-0 text-[11px] font-semibold uppercase ${
                      c.verdict === "RECHAZADA" ? "text-rose-300" : "text-emerald-300"
                    }`}
                  >
                    {c.verdict}
                  </span>
                  <span className="font-medium text-zinc-300">{c.estrategia ?? "—"}</span>
                  <span className="text-xs text-zinc-600">{c.instrumento}</span>
                  <span className="ml-auto text-xs text-zinc-600">{relativo(c.creado)}</span>
                </div>
                <p className="mt-0.5 pl-[5.5rem] text-xs text-zinc-500">{c.motivo}</p>
              </li>
            ))}
            {checks.length === 0 && <li className="py-3 text-sm text-zinc-600">Sin chequeos registrados.</li>}
          </ul>
        </Panel>

        <Panel titulo="Límites vigentes">
          <ul className="space-y-3">
            {LIMITES.map((l) => (
              <li key={l.nombre} className="rounded-lg border border-[var(--color-borde)] p-3">
                <p className="text-xs text-zinc-500">{l.nombre}</p>
                <p className="mt-0.5 text-sm font-medium text-zinc-200">{l.valor}</p>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] text-zinc-600">
            Los cambios de límites requieren doble confirmación del CEO y, en producción, se aplican vía
            directriz auditable (fase 4: escritura a config con validación).
          </p>
        </Panel>
      </div>
    </>
  );
}
