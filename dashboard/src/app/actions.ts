"use server";

// Acciones de gobierno del CEO. Según docs/arquitectura.md §3.7 y P2:
// los cambios de límites y modos exigen doble confirmación (se implementa en
// la UI con DoubleConfirm) y la autoridad es exclusiva del CEO.

import { revalidatePath } from "next/cache";
import { sql } from "@/lib/db";

export interface AccionResultado {
  ok: boolean;
  mensaje: string;
}

export async function crearDirectiva(formData: FormData): Promise<AccionResultado> {
  const texto = String(formData.get("texto") ?? "").trim();
  const scope = String(formData.get("scope") ?? "general");
  if (texto.length < 10) {
    return { ok: false, mensaje: "La directriz debe tener al menos 10 caracteres." };
  }

  if (!sql) {
    return { ok: true, mensaje: "Directriz registrada (demo: sin base de datos no se persiste)." };
  }
  try {
    await sql`
      INSERT INTO directives (id, ceo_id, text, scope, status)
      VALUES (gen_random_uuid(), 'ceo-dashboard', ${texto}, ${scope}, 'VIGENTE')
    `;
    revalidatePath("/directivas");
    revalidatePath("/");
    return { ok: true, mensaje: "Directriz publicada y vigente." };
  } catch (err) {
    console.error("[acciones] crearDirectiva:", err);
    return { ok: false, mensaje: "Error al escribir en la memoria colectiva." };
  }
}

export async function revocarDirectiva(id: string): Promise<AccionResultado> {
  if (!sql) {
    return { ok: true, mensaje: "Directriz revocada (demo: sin base de datos no se persiste)." };
  }
  try {
    await sql`UPDATE directives SET status = 'REVOCADA' WHERE id = ${id}`;
    revalidatePath("/directivas");
    return { ok: true, mensaje: "Directriz revocada." };
  } catch (err) {
    console.error("[acciones] revocarDirectiva:", err);
    return { ok: false, mensaje: "Error al revocar la directriz." };
  }
}

const TRANSICIONES: Record<string, string> = {
  pausar: "PAPEL", // pausa operativa: deja de operar, permanece en papel
  reactivar: "VIVA",
  retirar: "RETIRADA",
  bloquear: "BLOQUEADA",
};

export async function cambiarEstadoEstrategia(id: string, accion: keyof typeof TRANSICIONES): Promise<AccionResultado> {
  const nuevo = TRANSICIONES[accion];
  if (!nuevo) return { ok: false, mensaje: "Acción desconocida." };

  if (!sql) {
    return { ok: true, mensaje: `Estrategia → ${nuevo} (demo: sin base de datos no se persiste).` };
  }
  try {
    const rows = await sql`
      UPDATE strategies SET status = ${nuevo}::strategy_status, updated_at = now()
      WHERE id = ${id}
      RETURNING id
    `;
    if (rows.length === 0) return { ok: false, mensaje: "Estrategia no encontrada." };
    revalidatePath("/estrategias");
    revalidatePath("/pipeline");
    revalidatePath("/");
    return { ok: true, mensaje: `Estrategia movida a ${nuevo}.` };
  } catch (err) {
    console.error("[acciones] cambiarEstadoEstrategia:", err);
    return { ok: false, mensaje: "Error al actualizar la estrategia." };
  }
}

export async function cambiarModoSistema(modo: string): Promise<AccionResultado> {
  const validos = ["PAPER", "LIVE_CAPITAL_REDUCIDO", "LIVE"];
  if (!validos.includes(modo)) return { ok: false, mensaje: "Modo no válido." };

  if (!sql) {
    return { ok: true, mensaje: `Sistema en ${modo} (demo: sin base de datos no se persiste).` };
  }
  try {
    await sql`
      INSERT INTO directives (id, ceo_id, text, scope, status)
      VALUES (gen_random_uuid(), 'ceo-dashboard',
              ${`Modo del sistema: ${modo}. Con efecto inmediato.`}, 'modo', 'VIGENTE')
    `;
    revalidatePath("/");
    return { ok: true, mensaje: `Sistema en ${modo}. Registrado como directriz auditable.` };
  } catch (err) {
    console.error("[acciones] cambiarModoSistema:", err);
    return { ok: false, mensaje: "Error al cambiar el modo del sistema." };
  }
}
