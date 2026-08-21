import type { NextConfig } from "next";

const apiUrl = process.env.AGBUS_API_URL ?? "http://localhost:8766";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle so the Docker image can ship just
  // .next/standalone instead of the whole node_modules tree.
  output: "standalone",
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
