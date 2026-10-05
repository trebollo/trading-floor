// Capa de datos del dashboard: cada consulta intenta leer de la memoria
// colectiva (Postgres) y, si no hay DATABASE_URL o falla, sirve el dataset
// de demo. La UI etiqueta siempre la fuente.

import { sql } from "./db";
import {
  demoAlertas,
  demoAudit,
  demoDepartamentos,
  demoDirectives,
  demoEquity,
  demoEvaluations,
  demoKpis,
  demoRiskChecks,
  demoStrategies,
} from "./demo";
import type {
  AuditEntry,
  DataSource,
  Directive,
  Evaluation,
  Overview,
  RiskCheck,
  Strategy,
  StrategyStatus,
} from "./types";

export interface Resultado<T> {
  datos: T;
  fuente: DataSource;
}

async function conFallback<T>(live: () => Promise<T>, demo: T): Promise<Resultado<T>> {
  if (!sql) return { datos: demo, fuente: "demo" };
  try {
    return { datos: await live(), fuente: "live" };
  } catch (err) {
    console.error("[dashboard] consulta fallida, sirviendo demo:", err);
    return { datos: demo, fuente: "demo" };
  }
}

// ---------------------------------------------------------------------------
// Estrategias
// ---------------------------------------------------------------------------

export async function getStrategies(): Promise<Resultado<Strategy[]>> {
  return conFallback(async () => {
    const rows = (await sql!`
      SELECT id, spec_json, status, owner_agent, updated_at
      FROM strategies
      ORDER BY updated_at DESC
      LIMIT 100
    `) as unknown as FilaStrategy[];
    return rows.map((r) => estrategiaDesdeFila(r));
  }, demoStrategies);
}

type FilaStrategy = {
  id: string;
  spec_json: Record<string, unknown> | null;
  status: string;
  owner_agent: string;
  updated_at: Date;
};

function estrategiaDesdeFila(r: FilaStrategy): Strategy {
  const spec = r.spec_json ?? {};
  const metricas = (spec["metricas"] ?? spec["metrics"] ?? {}) as Record<string, number>;
  return {
    id: r.id,
    nombre: String(spec["nombre"] ?? spec["name"] ?? spec["id"] ?? r.id.slice(0, 8)),
    status: r.status as StrategyStatus,
    ownerAgent: r.owner_agent,
    instrumentos: Array.isArray(spec["instrumentos"]) ? (spec["instrumentos"] as string[]) : [],
    sharpe: metricas["sharpe"] ?? null,
    maxDd: metricas["max_dd_pct"] ?? null,
    actualizado: r.updated_at.toISOString(),
  };
}

// ---------------------------------------------------------------------------
// Pipeline de investigación
// ---------------------------------------------------------------------------

export async function getEvaluations(): Promise<Resultado<Evaluation[]>> {
  return conFallback(async () => {
    const rows = await sql!`
      SELECT e.id, s.spec_json, e.kind, e.verdict, e.created_at
      FROM evaluations e
      JOIN strategies s ON s.id = e.strategy_id
      ORDER BY e.created_at DESC
      LIMIT 50
    `;
    return rows.map((r) => ({
      id: r.id,
      estrategia: String(r.spec_json?.["nombre"] ?? r.spec_json?.["name"] ?? "—"),
      kind: r.kind,
      verdict: r.verdict,
      creado: r.created_at.toISOString(),
    }));
  }, demoEvaluations);
}

// ---------------------------------------------------------------------------
// Directrices
// ---------------------------------------------------------------------------

export async function getDirectives(): Promise<Resultado<Directive[]>> {
  return conFallback(async () => {
    const rows = await sql!`
      SELECT id, text, scope, status, ceo_id, effective_at
      FROM directives
      ORDER BY effective_at DESC
      LIMIT 50
    `;
    return rows.map((r) => ({
      id: r.id,
      texto: r.text,
      scope: r.scope,
      status: r.status,
      ceoId: r.ceo_id,
      efectiva: r.effective_at.toISOString(),
    }));
  }, demoDirectives);
}

// ---------------------------------------------------------------------------
// Riesgo
// ---------------------------------------------------------------------------

export async function getRiskChecks(): Promise<Resultado<RiskCheck[]>> {
  return conFallback(async () => {
    const rows = await sql!`
      SELECT rc.id, rc.verdict, rc.reason, rc.created_at,
             s.spec_json, o.instrument
      FROM risk_checks rc
      LEFT JOIN orders o ON o.id = rc.order_id
      LEFT JOIN strategies s ON s.id = o.strategy_id
      ORDER BY rc.created_at DESC
      LIMIT 50
    `;
    return rows.map((r) => ({
      id: r.id,
      estrategia: r.spec_json ? String(r.spec_json["nombre"] ?? r.spec_json["name"]) : null,
      instrumento: r.instrument ?? "—",
      verdict: r.verdict,
      motivo: r.reason,
      creado: r.created_at.toISOString(),
    }));
  }, demoRiskChecks);
}

// ---------------------------------------------------------------------------
// Auditoría
// ---------------------------------------------------------------------------

export async function getAudit(limit = 100): Promise<Resultado<AuditEntry[]>> {
  return conFallback(async () => {
    const rows = await sql!`
      SELECT seq, ts, actor, event_type, payload::text AS payload, hash
      FROM audit_log
      ORDER BY seq DESC
      LIMIT ${limit}
    `;
    return rows.map((r) => ({
      seq: Number(r.seq),
      ts: r.ts.toISOString(),
      actor: r.actor,
      eventType: r.event_type,
      payload: r.payload,
      hash: r.hash,
    }));
  }, demoAudit);
}

// ---------------------------------------------------------------------------
// Vista general
// ---------------------------------------------------------------------------

export async function getOverview(): Promise<Resultado<Overview>> {
  return conFallback(async (): Promise<Overview> => {
    // KPIs operativos. La curva de equity exige una serie de P&L que aún no
    // existe como tabla (fase 4: telemetría); se marca como pendiente.
    const [{ n }] = await sql!`SELECT count(*)::int AS n FROM strategies WHERE status = 'VIVA'`;
    const kpis = { ...demoKpis, estrategiasVivas: n };
    return { kpis, equity: [], alertas: [], departamentos: demoDepartamentos };
  }, {
    kpis: demoKpis,
    equity: demoEquity,
    alertas: demoAlertas,
    departamentos: demoDepartamentos,
  });
}
