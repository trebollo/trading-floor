"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ENLACES = [
  { href: "/", etiqueta: "La Oficina" },
  { href: "/resumen", etiqueta: "Resumen operativo" },
  { href: "/estrategias", etiqueta: "Estrategias" },
  { href: "/pipeline", etiqueta: "Pipeline de investigación" },
  { href: "/riesgo", etiqueta: "Riesgo" },
  { href: "/directivas", etiqueta: "Directrices" },
  { href: "/auditoria", etiqueta: "Auditoría" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 flex-col border-r border-[var(--color-borde)] bg-[var(--color-panel)]/60 lg:flex">
      <div className="flex h-14 items-center gap-2 border-b border-[var(--color-borde)] px-5">
        <span className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
        <span className="text-sm font-semibold tracking-wide">Trading Floor</span>
        <span className="ml-auto rounded border border-[var(--color-borde)] px-1.5 py-0.5 text-[10px] text-zinc-500">
          CEO
        </span>
      </div>
      <nav className="flex flex-1 flex-col gap-1 p-3">
        {ENLACES.map((e) => {
          const activo = pathname === e.href;
          return (
            <Link
              key={e.href}
              href={e.href}
              className={`rounded-lg px-3 py-2 text-sm transition-colors ${
                activo
                  ? "bg-emerald-500/10 text-emerald-300"
                  : "text-zinc-400 hover:bg-white/5 hover:text-zinc-200"
              }`}
            >
              {e.etiqueta}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-[var(--color-borde)] p-4 text-[11px] leading-relaxed text-zinc-600">
        Los cambios de límites y de modo requieren doble confirmación (P2).
      </div>
    </aside>
  );
}
