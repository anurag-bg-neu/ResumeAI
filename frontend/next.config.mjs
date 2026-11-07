/** @type {import('next').NextConfig} */

// Where the FastAPI backend listens. Override for a non-local backend.
const API_URL = process.env.RESUMEAI_API_URL ?? "http://localhost:8000";

const nextConfig = {
  // A cold first analysis (model load) can take ~30s; the dev proxy's
  // default timeout would cut it off.
  experimental: { proxyTimeout: 120_000 },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
