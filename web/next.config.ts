import type {NextConfig} from 'next';
import createNextIntlPlugin from 'next-intl/plugin';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Separate build output for test/production runs so a running `next dev` (which owns .next)
  // and a production build never overwrite each other.
  distDir: process.env.NEXT_DIST_DIR ?? '.next'
};
export default createNextIntlPlugin('./i18n/request.ts')(nextConfig);
