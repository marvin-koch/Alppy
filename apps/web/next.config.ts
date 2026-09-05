import type { NextConfig } from 'next';
import createNextIntlPlugin from 'next-intl/plugin';

const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');

/**
 * The API lives behind the same origin in production (one reverse proxy), so
 * the browser sends the session cookie without CORS. In development the API
 * runs on its own port and `ALPPY_API_ORIGIN` proxies `/api/v1` to it.
 */
const apiOrigin = process.env.ALPPY_API_ORIGIN;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@alppy/ui'],
  eslint: { ignoreDuringBuilds: true },
  async rewrites() {
    if (!apiOrigin) return [];
    return [{ source: '/api/v1/:path*', destination: `${apiOrigin}/api/v1/:path*` }];
  },
};

export default withNextIntl(nextConfig);
