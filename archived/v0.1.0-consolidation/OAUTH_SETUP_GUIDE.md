# OAuth & Authentication Setup Guide

## Overview

This guide covers the complete OAuth authentication setup using NextAuth.js and Authentik. Follow these steps to avoid common pitfalls.

## Prerequisites

- Authentik OAuth provider running (see `/authentik/README.md`)
- Docker network `ray-compute` created
- Environment variables configured

## Environment Variables

Create a `.env` file in the root directory:

```bash
# Network Configuration
TAILSCALE_IP=${TAILSCALE_IP}  # Your public IP or domain

# Authentik Configuration
AUTHENTIK_CLIENT_ID=ray-compute-api
AUTHENTIK_CLIENT_SECRET=your-secret-here  # Generate using: openssl rand -base64 96

# NextAuth Configuration
NEXTAUTH_SECRET=your-nextauth-secret  # Generate using: openssl rand -base64 32
NEXTAUTH_URL=http://${TAILSCALE_IP}:3002

# API URLs
NEXT_PUBLIC_API_URL=http://${TAILSCALE_IP}:8000
NEXT_PUBLIC_AUTHENTIK_URL=http://${TAILSCALE_IP}:9000
```

### ⚠️ CRITICAL: Public vs Internal URLs

**For browser/client access:**
- Use `NEXT_PUBLIC_AUTHENTIK_URL` with public IP/domain
- Example: `http://${TAILSCALE_IP}:9000`

**For container-to-container communication:**
- Use `AUTHENTIK_URL` with Docker service name
- Example: `http://authentik-server:9000`

This separation is essential for proper OAuth flow!

## NextAuth.js Configuration

### 1. Install Dependencies

```json
{
  "dependencies": {
    "next-auth": "^4.24.5"
  },
  "devDependencies": {
    "tailwindcss": "^3.4.0",
    "autoprefixer": "^10.4.16",
    "postcss": "^8.4.32",
    "tailwindcss-animate": "^1.0.7"  // ← REQUIRED!
  }
}
```

### 2. Create Auth API Route

**File:** `/web_ui/src/app/api/auth/[...nextauth]/route.ts`

```typescript
import NextAuth, { AuthOptions } from "next-auth";

const AUTHENTIK_URL = process.env.AUTHENTIK_URL;  // Internal
const NEXT_PUBLIC_AUTHENTIK_URL = process.env.NEXT_PUBLIC_AUTHENTIK_URL;  // Public

export const authOptions: AuthOptions = {
  providers: [
    {
      id: "authentik",
      name: "Authentik",
      type: "oauth",
      // BROWSER redirects use PUBLIC URL
      authorization: {
        url: `${NEXT_PUBLIC_AUTHENTIK_URL}/application/o/authorize/`,
        params: { scope: "openid profile email" }
      },
      // SERVER calls use INTERNAL URL
      token: `${AUTHENTIK_URL}/application/o/token/`,
      userinfo: `${AUTHENTIK_URL}/application/o/userinfo/`,
      // JWT validation endpoints
      issuer: `${AUTHENTIK_URL}/application/o/ray-compute/`,
      jwks_endpoint: `${AUTHENTIK_URL}/application/o/ray-compute/jwks/`,
      clientId: process.env.AUTHENTIK_CLIENT_ID,
      clientSecret: process.env.AUTHENTIK_CLIENT_SECRET,
      profile(profile) {
        return {
          id: profile.sub,
          name: profile.name || profile.preferred_username,
          email: profile.email,
        };
      },
    }
  ],
  callbacks: {
    async jwt({ token, account }) {
      if (account) {
        token.accessToken = account.access_token;
      }
      return token;
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken as string;
      return session;
    }
  },
  pages: {
    signIn: '/login',
  },
  session: {
    strategy: 'jwt',
    maxAge: 24 * 60 * 60, // 24 hours
  },
  debug: process.env.NODE_ENV === 'development',
};

const handler = NextAuth(authOptions);
export { handler as GET, handler as POST };
```

### 3. Add Session Provider

**File:** `/web_ui/src/app/providers.tsx`

```typescript
'use client';

import { SessionProvider } from 'next-auth/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());

  return (
    <SessionProvider>
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    </SessionProvider>
  );
}
```

### 4. Wrap App with Providers

**File:** `/web_ui/src/app/layout.tsx`

```typescript
import { Providers } from './providers';

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
```

### 5. Protect Routes with useSession

```typescript
'use client';

import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

export default function DashboardPage() {
  const router = useRouter();
  const { data: session, status } = useSession({
    required: true,
    onUnauthenticated() {
      router.push('/login');
    },
  });
  
  // CRITICAL: Prevent hydration mismatch
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  
  if (!mounted || status === "loading") {
    return <div>Loading...</div>;
  }
  
  return <div>Welcome {session.user?.name}!</div>;
}
```

## Tailwind CSS Setup

### 1. PostCSS Configuration (REQUIRED!)

**File:** `/web_ui/postcss.config.js`

```javascript
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

### 2. Tailwind Config

**File:** `/web_ui/tailwind.config.ts`

```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      // ... theme config
    },
  },
  plugins: [require("tailwindcss-animate")],  // ← REQUIRED!
};

export default config;
```

### 3. Global CSS

**File:** `/web_ui/src/app/globals.css`

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 222.2 84% 4.9%;
    /* ... CSS variables */
  }
}
```

## Docker Configuration

### Dockerfile

```dockerfile
FROM node:20-alpine AS base

FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install  # Includes devDependencies for Tailwind!

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED 1
RUN npm run build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV production
ENV NEXT_TELEMETRY_DISABLED 1

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# CRITICAL: Copy all three directories!
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
```

### docker-compose.ui.yml

```yaml
version: '3.8'

services:
  ray-compute-ui:
    build:
      context: ./web_ui
      dockerfile: Dockerfile
    container_name: ray-compute-ui
    restart: unless-stopped
    environment:
      - NEXT_PUBLIC_API_URL=http://${TAILSCALE_IP}:8000
      - NEXT_PUBLIC_AUTHENTIK_URL=http://${TAILSCALE_IP}:9000
      - AUTHENTIK_URL=http://authentik-server:9000  # Internal!
      - NEXTAUTH_URL=http://${TAILSCALE_IP}:3002
      - NEXTAUTH_SECRET=${NEXTAUTH_SECRET}
      - AUTHENTIK_CLIENT_ID=${AUTHENTIK_CLIENT_ID}
      - AUTHENTIK_CLIENT_SECRET=${AUTHENTIK_CLIENT_SECRET}
    ports:
      - "3002:3000"
    networks:
      - ray-compute
    healthcheck:
      test: ["CMD", "wget", "--spider", "http://localhost:3000"]
      interval: 30s
      timeout: 10s
      retries: 3

networks:
  ray-compute:
    name: ray-compute
    external: true
```

## Testing the Setup

### 1. Build and Start

```bash
cd /path/to/ray_compute
docker-compose -f docker-compose.ui.yml up -d --build
```

### 2. Check Logs

```bash
docker logs ray-compute-ui
# Should see: ✓ Ready in XXms
```

### 3. Verify CSS is Processed

```bash
docker exec ray-compute-ui sh -c 'wc -c /app/.next/static/css/*.css'
# Should be >15KB, not 3KB!
```

### 4. Test OAuth Flow

1. Go to `http://YOUR_IP:3002/`
2. Click "Sign in with Authentik"
3. Login with credentials
4. Should redirect to dashboard (no circular redirects!)

## Troubleshooting

### Circular Redirects

**Symptom:** Login redirects back to login page infinitely

**Check:**
- [ ] `NEXTAUTH_URL` matches your public URL
- [ ] Authentik redirect URI is configured: `http://YOUR_IP:3002/api/auth/callback/authentik`
- [ ] `issuer` and `jwks_endpoint` are set correctly
- [ ] No hydration errors in browser console

### Styles Not Loading

**Symptom:** Dashboard looks unstyled, plain HTML

**Check:**
- [ ] `postcss.config.js` exists
- [ ] `tailwindcss-animate` in package.json
- [ ] CSS file size >15KB
- [ ] Build logs show no CSS errors
- [ ] Browser Network tab shows CSS loading

### Container Can't Reach Authentik

**Symptom:** ECONNREFUSED errors in logs

**Check:**
- [ ] Both containers on same Docker network
- [ ] Using `authentik-server` hostname (not IP)
- [ ] Authentik container is running
- [ ] Test connectivity: `docker exec ray-compute-ui wget authentik-server:9000`

## Security Checklist

- [ ] `NEXTAUTH_SECRET` is strong random string
- [ ] `AUTHENTIK_CLIENT_SECRET` is stored in `.env`, not committed
- [ ] HTTPS enabled in production
- [ ] CORS configured properly
- [ ] Secure cookies enabled (`secure: true` in production)
- [ ] Rate limiting on auth endpoints
- [ ] Session expiry configured

## Next Steps

After authentication works:
1. Add API client with auth header injection
2. Implement logout functionality
3. Add session refresh logic
4. Set up user profile page
5. Add role-based access control

## Resources

- [NextAuth.js Documentation](https://next-auth.js.org/)
- [Authentik OAuth Provider](https://goauthentik.io/)
- [Next.js App Router](https://nextjs.org/docs/app)
- [Tailwind CSS](https://tailwindcss.com/)
