// @ts-nocheck
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Needed for small, production-ready Docker images (see Dockerfile).
  output: "standalone",
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
  async rewrites() {
    const base = process.env.CONFIG_SERVICE_URL;
    if (!base) return [];

    // Proxy identity endpoints and /api/v1/* directly to the config service.
    return [
      { source: "/api/auth/me", destination: `${base}/api/auth/me` },
      { source: "/api/whoami", destination: `${base}/api/whoami` },
      { source: "/api/config/identity", destination: `${base}/api/config/identity` },
      // Proxy all /api/v1/* endpoints to config service
      { source: "/api/v1/:path*", destination: `${base}/api/v1/:path*` },
      // Proxy GitHub App OAuth callback to config service
      // GitHub redirects here after app installation
      { source: "/github/callback", destination: `${base}/github/callback` },
      { source: "/github/installations/:path*", destination: `${base}/github/installations/:path*` },
    ];
  },
};

export default nextConfig;
