/**
 * Server-side proxy: browser -> this Next.js route -> FastAPI backend.
 *
 * - The backend URL and its API key stay server-side (never shipped to the browser).
 * - If APP_ACCESS_CODE is set, POST requests (which spend crawl time and Claude
 *   credits) must carry a matching `x-access-code` header.
 */
import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
const PASS_HEADERS = ["content-type", "content-disposition"];

async function proxy(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const accessCode = process.env.APP_ACCESS_CODE;
  if (req.method === "POST" && accessCode && req.headers.get("x-access-code") !== accessCode) {
    return Response.json({ detail: "Access code required or incorrect" }, { status: 401 });
  }

  const target = `${BACKEND_URL}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers: Record<string, string> = { "content-type": req.headers.get("content-type") ?? "application/json" };
  if (process.env.BACKEND_API_KEY) headers["x-api-key"] = process.env.BACKEND_API_KEY;
  const fwd = req.headers.get("x-forwarded-for");
  if (fwd) headers["x-forwarded-for"] = fwd;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer(),
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: "Audit service is unreachable. Check BACKEND_URL." }, { status: 502 });
  }
  const out = new Headers();
  for (const h of PASS_HEADERS) {
    const v = upstream.headers.get(h);
    if (v) out.set(h, v);
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as DELETE };
