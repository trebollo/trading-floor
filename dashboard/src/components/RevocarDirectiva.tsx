"use client";

import { revocarDirectiva } from "@/app/actions";
import { DoubleConfirm } from "@/components/DoubleConfirm";

export function RevocarDirectiva({ id }: { id: string }) {
  return (
    <DoubleConfirm
      etiqueta="Revocar"
      etiquetaConfirm="¿Confirmar revocación?"
      peligroso
      onConfirm={() => revocarDirectiva(id)}
    />
  );
}
