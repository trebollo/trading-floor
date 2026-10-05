"use client";

// Doble confirmación (P2/P4 de la arquitectura): el botón se arma con la
// primera pulsación y solo ejecuta con la segunda. Se desarma a los 4 s.

import { useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

export function DoubleConfirm({
  etiqueta,
  etiquetaConfirm,
  onConfirm,
  peligroso = false,
  className = "",
}: {
  etiqueta: string;
  etiquetaConfirm: string;
  onConfirm: () => Promise<{ ok: boolean; mensaje: string }>;
  peligroso?: boolean;
  className?: string;
}) {
  const [armado, setArmado] = useState(false);
  const [pendiente, startTransition] = useTransition();
  const [resultado, setResultado] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const router = useRouter();

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const click = () => {
    if (!armado) {
      setArmado(true);
      timer.current = setTimeout(() => setArmado(false), 4000);
      return;
    }
    if (timer.current) clearTimeout(timer.current);
    setArmado(false);
    startTransition(async () => {
      const r = await onConfirm();
      setResultado(r.mensaje);
      if (r.ok) router.refresh();
      setTimeout(() => setResultado(null), 5000);
    });
  };

  const base = peligroso
    ? "border-rose-500/40 text-rose-300 hover:bg-rose-500/10"
    : "border-[var(--color-borde)] text-zinc-300 hover:bg-white/5";

  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={click}
        disabled={pendiente}
        className={`rounded-lg border px-2.5 py-1 text-xs transition-colors disabled:opacity-50 ${
          armado ? "border-amber-400 bg-amber-400/10 text-amber-200" : base
        } ${className}`}
      >
        {pendiente ? "Aplicando…" : armado ? etiquetaConfirm : etiqueta}
      </button>
      {resultado && <span className="text-xs text-zinc-500">{resultado}</span>}
    </span>
  );
}
