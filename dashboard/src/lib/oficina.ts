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
  /** P&L del día atribuible al departamento (reparto determinista del global). */
  pnlDia: number;
}

/** Acontecimiento proyectado en el ticker de la oficina. */
export interface EventoOficina {
  id: string;
  ts: string;
  /** Departamento originador (null = sistema). */
  departamento: string | null;
  texto: string;
  nivel: "info" | "aviso" | "critico";
}

export interface OficinaData {
  fuente: DataSource;
  kpis: Kpis;
  equity: EquityPoint[];
  alertas: { nivel: "info" | "aviso" | "critico"; texto: string; ts: string }[];
  eventos: EventoOficina[];
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

/** Reparto del P&L del día entre salas (genera costes y beneficios atribuibles). */
const REPARTO_PNL: Record<string, number> = {
  execution: 0.85,
  macro: 0.35,
  risk: 0.06,
  research: -0.08,
  backtest: -0.04,
  validation: -0.04,
  direccion: -0.1,
};

/** Tareas secundarias que los agentes alternan en la simulación en vivo (demo). */
const TAREAS_EXTRA: Record<string, string[]> = {
  direccion: ["Preparando el resumen de las 20:00 para el CEO", "Revisando el presupuesto LLM del mes"],
  research: ["Filtrando la cola de hipótesis por expectancy", "Leyendo la memoria colectiva de fallos"],
  backtest: ["Encolando sprint de validación cruzada", "Ajustando costes de slippage del modelo"],
  validation: ["Walk-forward sobre ventanas de volatilidad", "Presionando la spec por sesgo de supervivencia"],
  risk: ["Recalibrando el límite de exposición bruta", "Auditando los vetos de la semana"],
  macro: ["Refrescando el calendario económico", "Reevaluando el régimen tras el CPI"],
  execution: ["Reconciliando fills del bloque de las 11:00", "Replaying el ledger contra el broker demo"],
};

/** Acontecimientos de sala que la simulación emite de vez en cuando (demo). */
const EVENTOS_SALA: Record<string, string[]> = {
  direccion: ["Informe diario entregado al CEO", "Directriz de presupuesto verificada por el gabinete"],
  research: ["Nueva hipótesis en cola: breakout-USDJPY-h4", "Hipótesis descartada por expectancy negativo"],
  backtest: ["Backtest completado: sharpe 1.31 · dd -7.2 %", "Backtest abortado: datos de sesión incompletos"],
  validation: ["Monte Carlo: p95 de dd dentro de umbrales", "El adversario ha encontrado sensibilidad a costes"],
  risk: ["Veto pre-trade: exposición bruta al límite", "Gate pre-trade: 12 órdenes autorizadas"],
  macro: ["Régimen reevaluado: risk-on moderado", "Calendario: impacto alto en 45 min (NFP)"],
  execution: ["3 órdenes enviadas · slippage 0.4 pb", "Ledger conciliado · replay verificado"],
};

function nivelDeEvento(texto: string): EventoOficina["nivel"] {
  if (/veto|abortad|impacto alto/i.test(texto)) return "aviso";
  return "info";
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
      pnlDia: Math.round(kpis.pnlDia * (REPARTO_PNL[sala.id] ?? 0) * 100) / 100,
    };
  });
}

/** Eventos iniciales de la sesión de demo (con timestamps recientes). */
function demoEventos(): EventoOficina[] {
  const ev = (minAtras: number, departamento: string | null, texto: string, nivel: EventoOficina["nivel"] = "info"): EventoOficina => ({
    id: `ev-inicial-${minAtras}-${departamento ?? "sys"}`,
    ts: new Date(Date.now() - minAtras * 60_000).toISOString(),
    departamento,
    texto,
    nivel,
  });
  return [
    ev(96, "direccion", "Apertura de sesión: modo PAPER, 4 estrategias vivas"),
    ev(74, "research", "Nueva hipótesis en cola: FX reversión a la media"),
    ev(63, "backtest", "Backtest en curso: stat-arb-pares-BBVA-SAN"),
    ev(41, "risk", "Veto pre-trade: exposición bruta", "aviso"),
    ev(33, "execution", "Órdenes de mean-reversion-EURUSD-m5 enviadas"),
    ev(18, "macro", "Calendario económico sin refrescar (2 h)", "aviso"),
    ev(6, "execution", "Ledger conciliado · replay verificado"),
  ];
}

export function demoOficina(): OficinaData {
  return {
    fuente: "demo",
    kpis: demoKpis,
    equity: demoEquity,
    alertas: demoAlertas,
    eventos: demoEventos(),
    departamentos: montarOficina(demoKpis, demoStrategies),
  };
}

// ---------------------------------------------------------------------------
// Simulación en vivo (solo demo): avanza la oficina un tick para que la
// escena respire mientras se depura la interfaz. Con memoria colectiva
// conectada, la telemetría real (fase 4) sustituirá a esta función.
// ---------------------------------------------------------------------------

const round2 = (v: number) => Math.round(v * 100) / 100;
const clampPct = (v: number) => Math.min(95, Math.max(4, v));

/** Avanza un tick la simulación: equity, KPIs, tareas de agentes y eventos. */
export function avanzarOficina(datos: OficinaData): OficinaData {
  const ahora = new Date().toISOString();
  const eventos: EventoOficina[] = [...datos.eventos];
  const emitir = (departamento: string | null, texto: string, nivel: EventoOficina["nivel"] = nivelDeEvento(texto)) =>
    eventos.push({ id: crypto.randomUUID(), ts: ahora, departamento, texto, nivel });

  // La equity deriva con un pequeño sesgo positivo; acotamos la serie.
  const eq = datos.equity;
  const ultimo = eq[eq.length - 1];
  const equity = Math.max(50_000, ultimo.equity + (Math.random() - 0.46) * 60);
  const pico = Math.max(ultimo.equity / (1 + ultimo.drawdownPct / 100), equity);
  const equityNueva = [
    ...eq.slice(-239),
    { ts: ahora, equity: round2(equity), drawdownPct: round2(((equity - pico) / pico) * 100) },
  ];
  const delta = equity - ultimo.equity;

  const kpis: Kpis = {
    ...datos.kpis,
    pnlDia: round2(datos.kpis.pnlDia + delta),
    pnlAcumulado: round2(datos.kpis.pnlAcumulado + delta),
    exposicionPct: round2(clampPct(datos.kpis.exposicionPct + (Math.random() - 0.5) * 2.4)),
    presupuestoUsadoPct: round2(Math.min(99, datos.kpis.presupuestoUsadoPct + Math.random() * 0.06)),
  };

  // Copia mutable de los agentes.
  const departamentos = datos.departamentos.map((d) => ({
    ...d,
    pnlDia: round2(kpis.pnlDia * (REPARTO_PNL[d.id] ?? 0)),
    agentes: d.agentes.map((a) => ({ ...a })),
  }));
  const agentes = departamentos.flatMap((d) => d.agentes.map((a) => ({ a, d })));

  // Un agente alterna tarea de vez en cuando.
  if (Math.random() < 0.4) {
    const candidatos = agentes.filter(({ a }) => a.estado !== "alerta");
    const elegido = candidatos[Math.floor(Math.random() * candidatos.length)];
    if (elegido) {
      const pool = TAREAS_EXTRA[elegido.d.id];
      const tarea = pool[Math.floor(Math.random() * pool.length)];
      if (tarea && tarea !== elegido.a.tarea) {
        elegido.a.tarea = tarea;
        elegido.a.estado = "trabajando";
        emitir(elegido.d.id, `${elegido.a.rol}: ${tarea.charAt(0).toLowerCase()}${tarea.slice(1)}`);
      }
    }
  }

  // Acontecimiento genérico de sala.
  if (Math.random() < 0.45) {
    const ids = Object.keys(EVENTOS_SALA);
    const id = ids[Math.floor(Math.random() * ids.length)];
    const pool = EVENTOS_SALA[id];
    const texto = pool[Math.floor(Math.random() * pool.length)];
    emitir(id, texto);
  }

  return { ...datos, kpis, equity: equityNueva, departamentos, eventos: eventos.slice(-40) };
}
