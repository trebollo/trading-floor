import postgres from "postgres";

/**
 * Cliente Postgres para entornos serverless.
 *
 * postgres.js abre conexiones perezosamente y con `max` bajo funciona bien en
 * funciones cortas (Vercel). En despliegue real, `DATABASE_URL` debe apuntar al
 * pooler del proveedor (Neon/Supabase); en local, al Postgres+TimescaleDB de
 * docker-compose.yml. Si no hay DATABASE_URL, `sql` es null y la app sirve
 * datos de demo (src/lib/demo.ts).
 */
export const sql = process.env.DATABASE_URL
  ? postgres(process.env.DATABASE_URL, {
      max: 5,
      idle_timeout: 20,
      connect_timeout: 10,
    })
  : null;
