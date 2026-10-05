"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { crearDirectiva } from "@/app/actions";

const SCOPES = ["general", "riesgo", "research", "portfolio", "modo"];

export function DirectiveForm() {
  const [texto, setTexto] = useState("");
  const [scope, setScope] = useState("general");
  const [pendiente, startTransition] = useTransition();
  const [mensaje, setMensaje] = useState<{ ok: boolean; texto: string } | null>(null);
  const router = useRouter();

  const enviar = (e: React.FormEvent) => {
    e.preventDefault();
    if (!texto.trim()) return;
    const fd = new FormData();
    fd.set("texto", texto);
    fd.set("scope", scope);
    startTransition(async () => {
      const r = await crearDirectiva(fd);
      setMensaje({ ok: r.ok, texto: r.mensaje });
      if (r.ok) {
        setTexto("");
        router.refresh();
      }
      setTimeout(() => setMensaje(null), 6000);
    });
  };

  return (
    <form onSubmit={enviar} className="space-y-3">
      <textarea
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        rows={3}
        placeholder="Instrucción para el sistema, p. ej.: «Reducir exposición bruta máxima al 50 % hasta fin de mes.»"
        className="w-full resize-none rounded-lg border border-[var(--color-borde)] bg-black/30 p-3 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-emerald-500/50 focus:outline-none"
      />
      <div className="flex items-center gap-2">
        <select
          value={scope}
          onChange={(e) => setScope(e.target.value)}
          className="rounded-lg border border-[var(--color-borde)] bg-black/30 px-2.5 py-1.5 text-xs text-zinc-300 focus:outline-none"
        >
          {SCOPES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={pendiente || texto.trim().length < 10}
          className="ml-auto rounded-lg bg-emerald-500/90 px-3.5 py-1.5 text-xs font-medium text-black transition-colors hover:bg-emerald-400 disabled:opacity-40"
        >
          {pendiente ? "Publicando…" : "Publicar directriz"}
        </button>
      </div>
      {mensaje && (
        <p className={`text-xs ${mensaje.ok ? "text-emerald-300" : "text-rose-300"}`}>{mensaje.texto}</p>
      )}
    </form>
  );
}
