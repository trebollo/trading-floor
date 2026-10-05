import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Serverless-first: sin dependencias nativas ni features experimentales.
  // El pool de Postgres se gestiona en src/lib/db.ts (postgres.js, max bajo).
};

export default nextConfig;
