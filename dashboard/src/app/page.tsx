import { getOverview, getStrategies } from "@/lib/data";
import { demoOficina, montarOficina } from "@/lib/oficina";
import { OficinaCanvas } from "@/components/oficina/OficinaCanvas";
import type { OficinaData } from "@/lib/oficina";

// Despliegue serverless: regeneración incremental cada 20 s.
export const revalidate = 20;

export default async function OficinaPage() {
  const [{ datos: overview, fuente }, { datos: estrategias }] = await Promise.all([
    getOverview(),
    getStrategies(),
  ]);

  // La plantilla de la oficina (puestos, posiciones) es de demo mientras no
  // exista telemetría de agentes (fase 4); los KPIs y el catálogo sí reflejan
  // la memoria colectiva cuando hay DATABASE_URL.
  const demo = demoOficina();
  const datos: OficinaData = {
    fuente,
    kpis: { ...demo.kpis, estrategiasVivas: overview.kpis.estrategiasVivas },
    equity: overview.equity.length > 0 ? overview.equity : demo.equity,
    alertas: overview.alertas.length > 0 ? overview.alertas : demo.alertas,
    departamentos: montarOficina({ ...demo.kpis, estrategiasVivas: overview.kpis.estrategiasVivas }, estrategias),
  };

  return (
    <div className="-m-6 lg:-m-8">
      <OficinaCanvas datos={datos} />
    </div>
  );
}
