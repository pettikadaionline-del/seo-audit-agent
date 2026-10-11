import type { NextConfig } from "next";

// Production: static export (out/) that the FastAPI app serves on the same origin as /api.
// Development: `next dev` proxies /api to the backend.
const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = isDev
  ? {
      async rewrites() {
        return [{ source: "/api/:path*", destination: `${process.env.BACKEND_URL ?? "http://localhost:8000"}/api/:path*` }];
      },
    }
  : { output: "export", trailingSlash: true, images: { unoptimized: true } };

export default nextConfig;
