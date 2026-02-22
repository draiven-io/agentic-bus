import type { NextConfig } from "next";

const apiUrl = process.env.AGBUS_API_URL ?? "http://localhost:8766";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/admin/:path*",
        destination: `${apiUrl}/api/admin/:path*`,
      },
    ];
  },
};

export default nextConfig;
