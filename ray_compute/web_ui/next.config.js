/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: false,
  basePath: '/ray/ui',
  assetPrefix: '/ray/ui',
  experimental: {
    appDir: true,
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
    NEXT_PUBLIC_AUTHENTIK_URL: process.env.NEXT_PUBLIC_AUTHENTIK_URL || 'http://localhost:9000',
  },
}

module.exports = nextConfig
