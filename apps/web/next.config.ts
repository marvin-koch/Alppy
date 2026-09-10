import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { NextConfig } from 'next';
import createNextIntlPlugin from 'next-intl/plugin';

import { STATIC_SECURITY_HEADERS } from './src/lib/csp';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');

/**
 * The API lives behind the same origin in production (one reverse proxy), so
 * the browser sends the session cookie without CORS. In development the API
 * runs on its own port and `ALPPY_API_ORIGIN` proxies `/api/v1` to it.
 */
const apiOrigin = process.env.ALPPY_API_ORIGIN;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Standalone only for the Docker image, which copies .next/standalone and
  // nothing else: no pnpm store, no source, no dev dependencies. It is opt-in
  // because `next start` refuses to serve a standalone build, and the e2e suite
  // wants a plain production server.
  ...(process.env.ALPPY_STANDALONE === '1'
    ? { output: 'standalone' as const, outputFileTracingRoot: path.join(__dirname, '../../') }
    : {}),
  transpilePackages: ['@alppy/ui'],
  eslint: { ignoreDuringBuilds: true },
  async rewrites() {
    if (!apiOrigin) return [];
    return [{ source: '/api/v1/:path*', destination: `${apiOrigin}/api/v1/:path*` }];
  },
  /**
   * The headers that do not vary per request. They belong here rather than in
   * the middleware because the middleware's matcher deliberately skips
   * `_next/*` and anything with a file extension, and `nosniff` on a script
   * bundle or an uploaded figure is exactly where it earns its keep.
   *
   * The Content-Security-Policy is NOT here: it carries a per-request nonce
   * and is set in `src/middleware.ts`.
   */
  async headers() {
    return [{ source: '/:path*', headers: [...STATIC_SECURITY_HEADERS] }];
  },
};

export default withNextIntl(nextConfig);
