// Tipos compartidos del dashboard. Espejan las tablas de migrations/0001_init.sql
// y los estados definidos en docs/arquitectura.md.

export type StrategyStatus =
  | "PROPUESTA"
  | "EN_BACKTEST"
  | "VALIDADA"
  | "APROBADA"
  | "PAPEL"
  | "VIVA"
  | "RETIRADA"
  | "BLOQUEADA";

export type SystemMode = "PAPER" | "LIVE_CAPITAL_REDUCIDO" | "LIVE";

export interface Strategy {
  id: string;
  nombre: string;
  status: StrategyStatus;
  ownerAgent: string;
  instrumentos: string[];
  sharpe: number | null;
  maxDd: number | null;
  actualizado: string; // ISO
}

export interface Evaluation {
  id: string;
  estrategia: string;
  kind: "backtest" | "validation" | "risk_review";
  verdict: string;
  creado: string; // ISO
}

export interface Directive {
  id: string;
  texto: string;
  scope: string;
  status: string;
  ceoId: string;
  efectiva: string; // ISO
}

export interface RiskCheck {
  id: string;
  estrategia: string | null;
  instrumento: string;
  verdict: string;
  motivo: string;
  creado: string; // ISO
}

export interface AuditEntry {
  seq: number;
  ts: string; // ISO
  actor: string;
  eventType: string;
  payload: string; // JSON en texto
  hash: string;
}

export interface Kpis {
  pnlDia: number;
  pnlAcumulado: number;
  exposicionPct: number;
  capital: number;
  estrategiasVivas: number;
  presupuestoUsadoPct: number;
  modo: SystemMode;
}

export interface EquityPoint {
  ts: string; // ISO
  equity: number;
  drawdownPct: number;
}

export interface DepartmentStatus {
  departamento: string;
  agentes: number;
  estado: "operativo" | "ocupado" | "degradado" | "pausado";
  detalle: string;
}

export interface Overview {
  kpis: Kpis;
  equity: EquityPoint[];
  alertas: Alerta[];
  departamentos: DepartmentStatus[];
}

export interface Alerta {
  id: string;
  nivel: "info" | "aviso" | "critico";
  texto: string;
  ts: string; // ISO
}

/** De dónde salen los datos de una petición. */
export type DataSource = "live" | "demo";
