// Dataset de demo: se sirve cuando no hay DATABASE_URL o la consulta falla,
// para que el dashboard sea navegable antes de conectar la memoria colectiva.
// Cada vista etiqueta la fuente ("demo" vs "live") en la UI.

import type {
  Alerta,
  AuditEntry,
  DepartmentStatus,
  Directive,
  EquityPoint,
  Evaluation,
  Kpis,
  RiskCheck,
  Strategy,
} from "./types";

const h = (horasAtras: number) =>
  new Date(Date.now() - horasAtras * 3600_000).toISOString();

export const demoKpis: Kpis = {
  pnlDia: 342.18,
  pnlAcumulado: 4812.9,
  exposicionPct: 38.5,
  capital: 100000,
  estrategiasVivas: 4,
  presupuestoUsadoPct: 62,
  modo: "PAPER",
};

export const demoEquity: EquityPoint[] = (() => {
  const puntos: EquityPoint[] = [];
  let equity = 96000;
  let pico = equity;
  for (let i = 30 * 24; i >= 0; i -= 4) {
    const ruido = (Math.sin(i * 1.7) + Math.cos(i * 0.43)) * 180;
    equity += 22 + ruido - (i % 97 < 12 ? 200 : 0);
    pico = Math.max(pico, equity);
    puntos.push({ ts: h(i), equity, drawdownPct: ((equity - pico) / pico) * 100 });
  }
  // Normaliza la serie para que sea coherente con los KPIs de demo:
  // capital + P&L acumulado al final, y una bajada inicial plausible.
  const objetivoFinal = demoKpis.capital + demoKpis.pnlAcumulado;
  const offset = objetivoFinal - puntos[puntos.length - 1].equity;
  return puntos.map((p) => ({
    ...p,
    equity: Math.round((p.equity + offset) * 100) / 100,
    drawdownPct: Math.round(p.drawdownPct * 100) / 100,
  }));
})();

export const demoStrategies: Strategy[] = [
  {
    id: "8f0e3a2c-1b4d-4e6f-9a01-2c3d4e5f6001",
    nombre: "mean-reversion-EURUSD-m5",
    status: "VIVA",
    ownerAgent: "research-hypothesis",
    instrumentos: ["EURUSD"],
    sharpe: 1.42,
    maxDd: -6.8,
    actualizado: h(2),
  },
  {
    id: "8f0e3a2c-1b4d-4e6f-9a01-2c3d4e5f6002",
    nombre: "momentum-breakout-SPX-d1",
    status: "VIVA",
    ownerAgent: "research-hypothesis",
    instrumentos: ["SPX"],
    sharpe: 1.18,
    maxDd: -9.4,
    actualizado: h(5),
  },
  {
    id: "8f0e3a2c-1b4d-4e6f-9a01-2c3d4e5f6003",
    nombre: "carry-BTCUSDT-h4",
    status: "PAPEL",
    ownerAgent: "research-hypothesis",
    instrumentos: ["BTCUSDT"],
    sharpe: 0.94,
    maxDd: -14.2,
    actualizado: h(9),
  },
  {
    id: "8f0e3a2c-1b4d-4e6f-9a01-2c3d4e5f6004",
    nombre: "vol-harvest-NQ-m15",
    status: "VALIDADA",
    ownerAgent: "research-coder",
    instrumentos: ["NQ"],
    sharpe: 1.61,
    maxDd: -7.9,
    actualizado: h(26),
  },
  {
    id: "8f0e3a2c-1b4d-4e6f-9a01-2c3d4e5f6005",
    nombre: "stat-arb-pares-BBVA-SAN",
    status: "EN_BACKTEST",
    ownerAgent: "research-coder",
    instrumentos: ["BBVA", "SAN"],
    sharpe: null,
    maxDd: null,
    actualizado: h(31),
  },
  {
    id: "8f0e3a2c-1b4d-4e6f-9a01-2c3d4e5f6006",
    nombre: "seasonality-OIL-w1",
    status: "BLOQUEADA",
    ownerAgent: "research-hypothesis",
    instrumentos: ["WTI"],
    sharpe: 0.51,
    maxDd: -21.3,
    actualizado: h(52),
  },
  {
    id: "8f0e3a2c-1b4d-4e6f-9a01-2c3d4e5f6007",
    nombre: "rsi-fade-EURJPY-h1",
    status: "RETIRADA",
    ownerAgent: "research-hypothesis",
    instrumentos: ["EURJPY"],
    sharpe: 0.77,
    maxDd: -18.6,
    actualizado: h(120),
  },
];

export const demoEvaluations: Evaluation[] = [
  { id: "e1", estrategia: "vol-harvest-NQ-m15", kind: "validation", verdict: "APROBADA", creado: h(26) },
  { id: "e2", estrategia: "stat-arb-pares-BBVA-SAN", kind: "backtest", verdict: "EN_CURSO", creado: h(30) },
  { id: "e3", estrategia: "carry-BTCUSDT-h4", kind: "risk_review", verdict: "CONDICIONADA", creado: h(34) },
  { id: "e4", estrategia: "seasonality-OIL-w1", kind: "validation", verdict: "RECHAZADA", creado: h(51) },
  { id: "e5", estrategia: "momentum-breakout-SPX-d1", kind: "backtest", verdict: "APROBADA", creado: h(72) },
];

export const demoDirectives: Directive[] = [
  {
    id: "d1",
    texto: "Reducir exposición bruta máxima al 60 % hasta cerrar el trimestre.",
    scope: "riesgo",
    status: "VIGENTE",
    ceoId: "ceo-local",
    efectiva: h(20),
  },
  {
    id: "d2",
    texto: "Priorizar hipótesis de reversión a la media en FX para el próximo ciclo.",
    scope: "research",
    status: "VIGENTE",
    ceoId: "ceo-local",
    efectiva: h(70),
  },
  {
    id: "d3",
    texto: "Congelar despliegue de nuevas estrategias de cripto hasta revisión del comité.",
    scope: "portfolio",
    status: "REVOCADA",
    ceoId: "ceo-local",
    efectiva: h(200),
  },
];

export const demoRiskChecks: RiskCheck[] = [
  {
    id: "r1",
    estrategia: "mean-reversion-EURUSD-m5",
    instrumento: "EURUSD",
    verdict: "APROBADA",
    motivo: "Riesgo 0.6% ≤ límite 1.0%, token válido",
    creado: h(0.4),
  },
  {
    id: "r2",
    estrategia: "momentum-breakout-SPX-d1",
    instrumento: "SPX",
    verdict: "RECHAZADA",
    motivo: "Exposición bruta alcanzaría 62% > 60% (directriz del CEO)",
    creado: h(1.1),
  },
  {
    id: "r3",
    estrategia: "carry-BTCUSDT-h4",
    instrumento: "BTCUSDT",
    verdict: "RECHAZADA",
    motivo: "Directriz: congelación de cripto hasta revisión del comité",
    creado: h(2.3),
  },
  {
    id: "r4",
    estrategia: "mean-reversion-EURUSD-m5",
    instrumento: "EURUSD",
    verdict: "APROBADA",
    motivo: "Riesgo 0.5% ≤ límite 1.0%, token válido",
    creado: h(3.8),
  },
];

export const demoAudit: AuditEntry[] = [
  { seq: 1042, ts: h(0.2), actor: "risk-pretrade", eventType: "risk.block", payload: '{"motivo":"exposicion"}', hash: "a3f1…" },
  { seq: 1041, ts: h(0.4), actor: "execution-router", eventType: "order.filled", payload: '{"instrument":"EURUSD","size":0.2}', hash: "b7c2…" },
  { seq: 1040, ts: h(1.1), actor: "risk-pretrade", eventType: "risk.block", payload: '{"motivo":"exposicion"}', hash: "9de4…" },
  { seq: 1039, ts: h(2.0), actor: "validation-quant", eventType: "evaluation.approved", payload: '{"strategy":"vol-harvest-NQ-m15"}', hash: "1fa8…" },
  { seq: 1038, ts: h(5.5), actor: "research-curator", eventType: "queue.prioritized", payload: '{"hipotesis":3}', hash: "44cd…" },
  { seq: 1037, ts: h(8.0), actor: "cost-governor", eventType: "budget.warning", payload: '{"uso":"58%"}', hash: "e20b…" },
];

export const demoDepartamentos: DepartmentStatus[] = [
  { departamento: "Dirección", agentes: 1, estado: "operativo", detalle: "Directrices vigentes: 2" },
  { departamento: "Research Lab", agentes: 3, estado: "ocupado", detalle: "3 hipótesis en cola" },
  { departamento: "Backtest Dept", agentes: 2, estado: "ocupado", detalle: "1 backtest en curso" },
  { departamento: "Validation Dept", agentes: 2, estado: "operativo", detalle: "Batería canónica al día" },
  { departamento: "Risk Dept", agentes: 1, estado: "operativo", detalle: "Gate activo, 2 vetos hoy" },
  { departamento: "Execution & Ops", agentes: 2, estado: "operativo", detalle: "Ledger conciliado" },
  { departamento: "Macro & News", agentes: 2, estado: "degradado", detalle: "Calendario económico sin refrescar (2 h)" },
];

export const demoAlertas: Alerta[] = [
  { id: "a1", nivel: "aviso", texto: "Macro & News sin refrescar calendario económico en 2 h.", ts: h(2) },
  { id: "a2", nivel: "critico", texto: "Risk Dept vetó 2 órdenes por exposición bruta (62% > 60%).", ts: h(1.2) },
  { id: "a3", nivel: "info", texto: "vol-harvest-NQ-m15 aprobó la batería de validación completa.", ts: h(26) },
  { id: "a4", nivel: "aviso", texto: "Presupuesto LLM al 62 % del techo diario (5 €).", ts: h(1) },
];
