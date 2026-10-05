import type { DataSource } from "@/lib/types";

/** Indica si la vista se alimenta de la memoria colectiva o del dataset de demo. */
export function FuenteBadge({ fuente }: { fuente: DataSource }) {
  const demo = fuente === "demo";
  return (
    <span
      title={demo ? "Sin DATABASE_URL: se sirven datos de ejemplo" : "Datos leídos de la memoria colectiva (Postgres)"}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] ${
        demo
          ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
          : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${demo ? "bg-amber-400" : "bg-emerald-400"}`} />
      {demo ? "Datos de demo" : "Datos en vivo"}
    </span>
  );
}

export function PageHeader({
  titulo,
  descripcion,
  fuente,
  acciones,
}: {
  titulo: string;
  descripcion?: string;
  fuente: DataSource;
  acciones?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">{titulo}</h1>
          <FuenteBadge fuente={fuente} />
        </div>
        {descripcion && <p className="mt-1 max-w-2xl text-sm text-zinc-500">{descripcion}</p>}
      </div>
      {acciones}
    </div>
  );
}

export function Panel({
  titulo,
  className = "",
  children,
}: {
  titulo?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className={`rounded-xl border border-[var(--color-borde)] bg-[var(--color-panel)]/70 p-5 shadow-[0_1px_0_rgba(255,255,255,0.03)_inset] ${className}`}
    >
      {titulo && <h2 className="mb-4 text-sm font-medium text-zinc-300">{titulo}</h2>}
      {children}
    </section>
  );
}

export function StatCard({
  etiqueta,
  valor,
  detalle,
  tono = "neutral",
}: {
  etiqueta: string;
  valor: string;
  detalle?: string;
  tono?: "neutral" | "positivo" | "negativo" | "aviso";
}) {
  const tonos = {
    neutral: "text-zinc-100",
    positivo: "text-emerald-300",
    negativo: "text-rose-300",
    aviso: "text-amber-300",
  };
  return (
    <div className="rounded-xl border border-[var(--color-borde)] bg-[var(--color-panel)]/70 p-4">
      <p className="text-xs text-zinc-500">{etiqueta}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tonos[tono]}`}>{valor}</p>
      {detalle && <p className="mt-0.5 text-xs text-zinc-600">{detalle}</p>}
    </div>
  );
}
