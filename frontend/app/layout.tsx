import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "SEO Audit Agent",
  description: "AI-powered technical, on-page, content and AI-search SEO audits",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <Link href="/" className="brand">
            SEO Audit Agent
          </Link>
          <span className="muted">Technical · On-page · Content · Performance · Schema · AI search</span>
        </header>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
