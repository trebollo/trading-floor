import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Trading Floor — Dashboard CEO",
  description: "Gobierno y observabilidad del sistema multiagente de trading.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body className="min-h-screen antialiased">
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 lg:pl-64">
            <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b border-[var(--color-borde)] bg-[var(--color-lienzo)]/80 px-6 backdrop-blur">
              <div className="flex items-center gap-3">
                <Link href="/" className="text-sm font-semibold tracking-wide text-zinc-200 lg:hidden">
                  Trading Floor
                </Link>
                <span className="hidden text-sm text-zinc-500 lg:block">
                  Autoridad: CEO · toda acción queda registrada
                </span>
              </div>
            </header>
            <div className="p-6 lg:p-8">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
