import type { NextConfig } from 'next';
import os from 'os';

// Next dev mode rejects cross-origin requests for its dev resources unless the host is
// allowed. Allow this machine's LAN addresses so other devices can use `next dev` too.
const lanHosts = Object.values(os.networkInterfaces())
  .flat()
  .filter((ni): ni is os.NetworkInterfaceInfo => Boolean(ni) && ni!.family === 'IPv4' && !ni!.internal)
  .map((ni) => ni.address);

// Serve the app under a path prefix (e.g. /smartfinder behind a reverse proxy); empty = root.
// Read at build time. Next prefixes pages, <Link>, router and /_next itself; the app adds it
// to fetch() (src/instrumentation-client.ts) and to <img>/<a> URLs (src/lib/base-path.ts).
const basePath = process.env.NEXT_BASE_PATH || '';

const nextConfig: NextConfig = {
  basePath,
  env: { NEXT_PUBLIC_BASE_PATH: basePath },
  allowedDevOrigins: [
    ...lanHosts,
    '0fa5-2409-40f2-2173-7fc2-b005-6255-ac33-2762.ngrok-free.app',
    '*.ngrok-free.app',
  ],
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: 'i.ytimg.com' },
      { protocol: 'https', hostname: 'img.youtube.com' },
      { protocol: 'https', hostname: 'picsum.photos' },
      { protocol: 'https', hostname: '**.googleusercontent.com' },
      { protocol: 'https', hostname: '**.newsapi.org' },
    ],
  },
  async rewrites() {
    // The Python backend listens on loopback only; Next is the network-facing entry point.
    const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
  experimental: {
    // Next copies every proxied request body into memory and truncates it at this size.
    // Uploads travel in 8 MB chunks (src/lib/upload/chunked-uploader.ts), so this only
    // needs to fit one chunk or a search query's attached file.
    proxyClientMaxBodySize: '64mb',
    proxyTimeout: 1000 * 60 * 120, // 2 hours - long-running searches and uploads
  },
};

export default nextConfig;
