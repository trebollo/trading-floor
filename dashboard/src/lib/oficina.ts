// Modelo de la escena "oficina": la empresa como espacio isométrico.
// Cada departamento es una sala con agentes-persona en su mesa; la Wall es la
// pantalla norte que proyecta las métricas. Los datos son de demo salvo que
// haya DATABASE_URL (mismo contrato que el resto del dashboard).

import type { DataSource, EquityPoint, Kpis, Strategy, StrategyStatus } from "./types";
import { demoAlertas, demoDepartamentos, demoEquity, demoKpis, demoStrategies } from "./demo";

export type EstadoAgente = "trabajando" | "activo" | "alerta";

export interface AgenteOficina {
  id: string;
  nombre: string; // id del agente en config/guardrails.yaml
  rol: string; // etiqueta legible
  departamento: string;
  estado: EstadoAgente;
  tarea: string;
  /** Posición en el mundo (coordenadas de tile), frente a su mesa. */
  x: number;
  y: number;
  fase: number; // desfase de animación
}

export interface DeptoOficina {
  id: string;
  nombre: string;
  descripcion: string;
  color: string; // acento de la sala
  /** Rectángulo en tiles: esquina noroeste + tamaño. */
  x: number;
  y: number;
  w: number;
  h: number;
  estado: "operativo" | "ocupado" | "degradado" | "pausado";
  detalle: string;
  agentes: AgenteOficina[];
  /** Estrategias en las que trabaja el departamento (se resuelve con el catálogo). */
  estrategias: Strategy[];
}

export interface OficinaData {
  fuente: DataSource;
  kpis: Kpis;
  equity: EquityPoint[];
  alertas: { nivel: "info" | "aviso" | "critico"; texto: string; ts: string }[];
  departamentos: DeptoOficina[];
}

// ---------------------------------------------------------------------------
// Plantilla: agentes por departamento, con su puesto en la sala.
// Las posiciones son relativas a la sala y el ensamblador las absolutiza.
// ---------------------------------------------------------------------------

interface Puesto {
  nombre: string;
  rol: string;
  estado: EstadoAgente;
  tarea: string;
  /** Offset en tiles desde la esquina NW de la sala. */
  dx: number;
  dy: number;
}

const PLANTILLA: Record<string, { puestos: Puesto[]; color: string }> = {
  direccion: {
    color: "#f59e0b",
    puestos: [
      { nombre: "chief-of-staff", rol: "Jefe de Gabinete", estado: "trabajando", tarea: "Redactando el informe diario para el CEO", dx: 3.2, dy: 1.6 },
      { nombre: "budget-governor", rol: "Cost Governor", estado: "activo", tarea: "Presupuesto LLM al 62 % — sin alertas", dx: 5.6, dy: 1.6 },
    ],
  },
  research: {
    color: "#38bdf8",
    puestos: [
      { nombre: "research-hypothesis", rol: "Hipótesis", estado: "trabajando", tarea: "3 hipótesis en cola · FX reversión a la media", dx: 2.4, dy: 1.6 },
      { nombre: "research-coder", rol: "Coder", estado: "trabajando", tarea: "Especificando stat-arb-pares-BBVA-SAN", dx: 4.8, dy: 1.6 },
      { nombre: "research-curator", rol: "Curador", estado: "activo", tarea: "Priorizando cola con la memoria colectiva", dx: 7.2, dy: 1.6 },
    ],
  },
  backtest: {
    color: "#818cf8",
    puestos: [
      { nombre: "backtest-engineer", rol: "Ingeniero de backtest", estado: "trabajando", tarea: "Corriendo backtest: stat-arb-pares-BBVA-SAN", dx: 2.4, dy: 1.6 },
      { nombre: "backtest-analyst", rol: "Analista", estado: "activo", tarea: "En espera de resultados con costes realistas", dx: 4.8, dy: 1.6 },
    ],
  },
  validation: {
    color: "#a78bfa",
    puestos: [
      { nombre: "validation-quant", rol: "Quant", estado: "trabajando", tarea: "Batería canónica: vol-harvest-NQ-m15", dx: 2.4, dy: 1.6 },
      { nombre: "validation-skeptic", rol: "Adversario", estado: "trabajando", tarea: "Atacando la spec por sensibilidad de costes", dx: 4.8, dy: 1.6 },
    ],
  },
  risk: {
    color: "#fb7185",
    puestos: [
      { nombre: "risk-pretrade", rol: "Gate pre-trade", estado: "alerta", tarea: "2 vetos hoy: exposición bruta y congelación cripto", dx: 3.2, dy: 1.6 },
    ],
  },
  execution: {
    color: "#34d399",
    puestos: [
      { nombre: "execution-router", rol: "Router", estado: "trabajando", tarea: "Órdenes de mean-reversion-EURUSD-m5 en curso", dx: 2.4, dy: 1.6 },
      { nombre: "ops-controller", rol: "Contabilidad", estado: "activo", tarea: "Ledger conciliado · replay verificado", dx: 4.8, dy: 1.6 },
    ],
  },
  macro: {
    color: "#22d3ee",
    puestos: [
      { nombre: "macro-analyst", rol: "Regímenes", estado: "activo", tarea: "Régimen actual: risk-on moderado", dx: 2.4, dy: 1.6 },
      { nombre: "news-triage", rol: "Triaje de noticias", estado: "alerta", tarea: "Calendario económico sin refrescar (2 h)", dx: 4.8, dy: 1.6 },
    ],
  },
};

// Sala: esquina NW (x, y) y tamaño (w, h) en tiles. Atrio central despejado.
const SALAS: { id: string; nombre: string; descripcion: string; estado: DeptoOficina["estado"]; detalle: string; x: number; y: number; w: number; h: number }[] = [
  { id: "direccion", nombre: "Dirección", descripcion: "Executive Suite: directrices, informes y presupuestos", estado: "operativo", detalle: "2 directrices vigentes", x: -3.5, y: -7.5, w: 7, h: 3.5 },
  { id: "research", nombre: "Research Lab", descripcion: "Hipótesis y especificaciones de estrategias", estado: "ocupado", detalle: "3 hipótesis en cola", x: -14.5, y: -7.5, w: 10.5, h: 4 },
  { id: "backtest", nombre: "Backtest Dept", descripcion: "Evaluación histórica con costes realistas", estado: "ocupado", detalle: "1 backtest en curso", x: 4, y: -7.5, w: 10.5, h: 4 },
  { id: "validation", nombre: "Validation Dept", descripcion: "Monte Carlo, walk-forward y adversario", estado: "operativo", detalle: "Batería canónica al día", x: -14.5, y: -1.5, w: 10.5, h: 3.5 },
  { id: "risk", nombre: "Risk Dept", descripcion: "Gate pre-trade y veto absoluto (P2)", estado: "operativo", detalle: "2 vetos hoy", x: 4, y: -1.5, w: 10.5, h: 3.5 },
  { id: "macro", nombre: "Macro & News", descripcion: "Regímenes, noticias y calendario", estado: "degradado", detalle: "Calendario sin refrescar (2 h)", x: -14.5, y: 4, w: 10.5, h: 3.5 },
  { id: "execution", nombre: "Execution & Ops", descripcion: "Órdenes, reconciliación y contabilidad", estado: "operativo", detalle: "Ledger conciliado", x: 4, y: 4, w: 10.5, h: 3.5 },
];

/** Agente → estrategia propietaria (owner_agent de la tabla strategies). */
function estrategiasDeDepto(deptoId: string, catalogo: Strategy[]): Strategy[] {
  const deAgente: Record<string, string> = {
    research: "research-hypothesis",
    backtest: "backtest-engineer",
    validation: "validation-quant",
    execution: "execution-router",
  };
  const owner = deAgente[deptoId];
  if (!owner) return [];
  return catalogo.filter((s) => s.ownerAgent === owner);
}

export function montarOficina(kpis: Kpis, catalogo: Strategy[]): DeptoOficina[] {
  return SALAS.map((sala) => {
    const plantilla = PLANTILLA[sala.id];
    const agentes: AgenteOficina[] = plantilla.puestos.map((p, i) => ({
      id: `${sala.id}:${p.nombre}`,
      nombre: p.nombre,
      rol: p.rol,
      departamento: sala.id,
      estado: p.estado,
      tarea: p.tarea,
      x: sala.x + p.dx,
      y: sala.y + p.dy,
      fase: i * 1.9 + sala.x,
    }));
    return {
      ...sala,
      color: plantilla.color,
      agentes,
      estrategias: estrategiasDeDepto(sala.id, catalogo),
    };
  });
}

export function demoOficina(): OficinaData {
  return {
    fuente: "demo",
    kpis: demoKpis,
    equity: demoEquity,
    alertas: demoAlertas,
    departamentos: montarOficina(demoKpis, demoStrategies),
  };
}
