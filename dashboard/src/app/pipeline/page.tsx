import { getEvaluations, getStrategies } from "@/lib/data";
import { ESTADO_ESTILO, relativo } from "@/lib/format";
import { PageHeader, Panel } from "@/components/ui";
import type { StrategyStatus } from "@/lib/types";

export const revalidate = 20;

// Embudo del ciclo de vida, en el orden del enum de migrations/0001_init.sql.
const ETAPAS: StrategyStatus[] = ["PROPUESTA", "EN_BACKTEST", "VALIDADA", "APROBADA", "PAPEL", "VIVA"];

const VERDICT_ESTILO: Record<string, string> = {
  APROBADA: "text-emerald-300",
  EN_CURSO: "text-sky-300",
  CONDICIONADA: "text-amber-300",
  RECHAZADA: "text-rose-300",
};

export default async function PipelinePage() {
  const [{ datos: estrategias, fuente }, { datos: evaluaciones }] = await Promise.all([
    getStrategies(),
    getEvaluations(),
  ]);

  const porEstado = new Map<StrategyStatus, number>();
  for (const e of estrategias) porEstado.set(e.status, (porEstado.get(e.status) ?? 0) + 1);
  const max = Math.max(1, ...ETAPAS.map((s) => porEstado.get(s) ?? 0));

  return (
    <>
      <PageHeader
        titulo="Pipeline de investigación"
        descripcion="Ciclo de vida de una estrategia: hipótesis → backtest → validación canónica → comité de riesgos → papel → viva."
        fuente={fuente}
      />

      <Panel titulo="Embudo por etapa">
        <div className="space-y-2.5">
          {ETAPAS.map((etapa) => {
            const n = porEstado.get(etapa) ?? 0;
            return (
              <div key={etapa} className="flex items-center gap-3">
                <span className="w-28 text-right text-xs text-zinc-400">{ESTADO_ESTILO[etapa].etiqueta}</span>
                <div className="h-7 flex-1 overflow-hidden rounded-md bg-white/5">
                  <div
                    className="flex h-full items-center rounded-md bg-gradient-to-r from-emerald-500/50 to-sky-500/40 px-2 text-xs text-white transition-all"
                    style={{ width: `${Math.max((n / max) * 100, n > 0 ? 6 : 0)}%` }}
                  >
                    {n > 0 ? n : ""}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        {(porEstado.get("RETIRADA") ?? 0) + (porEstado.get("BLOQUEADA") ?? 0) > 0 && (
          <p className="mt-3 text-xs text-zinc-600">
            Fuera del ciclo: {porEstado.get("RETIRADA") ?? 0} retiradas · {porEstado.get("BLOQUEADA") ?? 0} bloqueadas.
          </p>
        )}
      </Panel>

      <div className="mt-6">
        <Panel titulo="Evaluaciones recientes">
          <ul className="divide-y divide-[var(--color-borde)]/50">
            {evaluaciones.map((ev) => (
              <li key={ev.id} className="flex items-center gap-3 py-2.5 text-sm">
                <span className="w-20 text-[11px] uppercase tracking-wide text-zinc-600">{ev.kind}</span>
                <span className="flex-1 text-zinc-300">{ev.estrategia}</span>
                <span className={`text-xs font-medium ${VERDICT_ESTILO[ev.verdict] ?? "text-zinc-300"}`}>
                  {ev.verdict}
                </span>
                <span className="w-24 text-right text-xs text-zinc-600">{relativo(ev.creado)}</span>
              </li>
            ))}
            {evaluaciones.length === 0 && <li className="py-3 text-sm text-zinc-600">Sin evaluaciones.</li>}
          </ul>
        </Panel>
      </div>
    </>
  );
}
