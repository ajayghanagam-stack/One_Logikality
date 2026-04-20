import type { NextConfig } from "next";

// FastAPI runs on :8001; proxying /api/* through Next avoids CORS in dev
// and keeps the browser talking to a single origin (:9999). See
// docs/TechStack.md §11–12 for port allocation.
const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8001";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_ORIGIN}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
