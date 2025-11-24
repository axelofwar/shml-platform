# Lessons Learned: Ray Compute OAuth & UI Development

## Critical Issues Encountered and Solutions

### 1. OAuth Authentication Circular Redirects

**Problem:**
- Users stuck in infinite redirect loop between login page and OAuth callback
- Session not persisting after successful Authentik authentication

**Root Causes:**
1. Missing NextAuth.js configuration
2. Incorrect OAuth endpoint URLs (internal vs public)
3. Missing issuer and JWKS endpoint configuration
4. React hydration mismatches causing component failures

**Solution:**
```typescript
// Use NextAuth.js with manual endpoint configuration
const authOptions: AuthOptions = {
  providers: [
    {
      id: "authentik",
      name: "Authentik",
      type: "oauth",
      // CRITICAL: Use public URL for browser redirects
      authorization: {
        url: `${NEXT_PUBLIC_AUTHENTIK_URL}/application/o/authorize/`,
        params: { scope: "openid profile email" }
      },
      // CRITICAL: Use internal Docker URL for server-side calls
      token: `${AUTHENTIK_URL}/application/o/token/`,
      userinfo: `${AUTHENTIK_URL}/application/o/userinfo/`,
      // CRITICAL: These prevent JWT validation errors
      issuer: `${AUTHENTIK_URL}/application/o/ray-compute/`,
      jwks_endpoint: `${AUTHENTIK_URL}/application/o/ray-compute/jwks/`,
      clientId: process.env.AUTHENTIK_CLIENT_ID,
      clientSecret: process.env.AUTHENTIK_CLIENT_SECRET,
    }
  ],
  // CRITICAL: Store tokens in session for API calls
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
  }
};
```

**Prevention:**
- Always use industry-standard auth libraries (NextAuth.js) instead of manual OAuth
- Separate public URLs (browser access) from internal URLs (container-to-container)
- Configure issuer and JWKS endpoints explicitly when OAuth provider is self-hosted
- Test OAuth flow end-to-end before adding complex UI

---

### 2. React Hydration Mismatch (Error #310)

**Problem:**
```
Minified React error #310
Text content does not match server-rendered HTML
```

**Root Causes:**
1. Component accessing `window`, `localStorage`, or `sessionStorage` during SSR
2. Conditional rendering based on client-side state during initial render
3. Different content rendered on server vs client

**Solution:**
```typescript
export default function Component() {
  const [mounted, setMounted] = useState(false);
  
  useEffect(() => {
    setMounted(true);
  }, []);
  
  // Return consistent structure until mounted
  if (!mounted || status === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-muted-foreground">Loading...</div>
      </div>
    );
  }
  
  // Client-only rendering after mount
  return <ActualComponent />;
}
```

**Prevention:**
- Never access browser APIs (`window`, `localStorage`, `document`) in component body
- Use `useEffect` for all client-side-only code
- Return consistent DOM structure during SSR and initial client render
- Use `suppressHydrationWarning` only as last resort with proper justification

---

### 3. Tailwind CSS Not Loading in Production

**Problem:**
- CSS file only 3KB with `@tailwind` directives unprocessed
- Styles not applied in production Docker build
- Development mode worked fine

**Root Causes:**
1. **Missing `tailwindcss-animate` package** in dependencies
2. **Tailwind in `devDependencies`** but Docker production build doesn't install dev deps
3. Missing `postcss.config.js` file
4. `npm ci` failing without package-lock.json

**Solution:**
```json
// package.json - Add missing package
{
  "devDependencies": {
    "tailwindcss": "^3.4.0",
    "autoprefixer": "^10.4.16",
    "postcss": "^8.4.32",
    "tailwindcss-animate": "^1.0.7"  // <-- THIS WAS MISSING
  }
}
```

```javascript
// postcss.config.js - REQUIRED for Tailwind processing
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

```dockerfile
# Dockerfile - Use npm install to include devDependencies during build
RUN npm install  # NOT npm ci --production
```

**Prevention:**
- Always include PostCSS config file when using Tailwind
- Keep Tailwind in devDependencies but ensure build process installs them
- Test production Docker builds locally before deploying
- Check that `tailwind.config.ts` has all required plugins listed
- Verify CSS file size after build (should be 15-50KB+, not 3KB)

---

### 4. Docker Networking: Internal vs Public URLs

**Problem:**
- Browser could access services but containers couldn't communicate
- OAuth callbacks failing with ECONNREFUSED
- Mixed usage of localhost, 127.0.0.1, and hostnames

**Solution:**
```yaml
# docker-compose.yml
environment:
  # Public URL for browser/client redirects
  - NEXT_PUBLIC_AUTHENTIK_URL=http://${TAILSCALE_IP}:9000
  # Internal URL for container-to-container communication
  - AUTHENTIK_URL=http://authentik-server:9000
  
networks:
  ray-compute:
    name: ray-compute
    external: true
```

**Prevention:**
- Use separate environment variables for public and internal URLs
- Prefix client-visible URLs with `NEXT_PUBLIC_` in Next.js
- Always use Docker service names for container-to-container communication
- Test both browser access AND internal API calls
- Document network architecture clearly

---

### 5. Next.js Standalone Build Configuration

**Problem:**
- Static files not copied correctly
- Environment variables not available at runtime
- Large image size with unnecessary files

**Solution:**
```javascript
// next.config.js
const nextConfig = {
  output: 'standalone',  // Minimal production output
  reactStrictMode: false, // Disable if causing issues in prod
  experimental: {
    appDir: true,
  },
  env: {
    // Only for build-time values
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_AUTHENTIK_URL: process.env.NEXT_PUBLIC_AUTHENTIK_URL,
  },
}
```

```dockerfile
# Dockerfile - Multi-stage build
FROM node:20-alpine AS deps
RUN npm install

FROM node:20-alpine AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
# CRITICAL: Copy both standalone AND static files
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
```

**Prevention:**
- Always use multi-stage Docker builds for Next.js
- Copy `.next/standalone`, `.next/static`, and `public` separately
- Use environment variables at runtime, not build time when possible
- Test Docker image by running it locally before deploying

---

## Development Best Practices Learned

### Authentication Flow
1. ✅ Use NextAuth.js for production OAuth implementations
2. ✅ Never store tokens in localStorage (XSS vulnerability)
3. ✅ Always use HTTP-only cookies for session management
4. ✅ Validate JWT tokens on every API request
5. ✅ Configure CORS properly for cross-origin requests

### React/Next.js Development
1. ✅ Avoid hydration mismatches by using mounting guards
2. ✅ Use `"use client"` directive for components with browser APIs
3. ✅ Keep server components when possible for better performance
4. ✅ Test SSR and CSR separately during development
5. ✅ Use TypeScript for type safety and better DX

### Docker & Deployment
1. ✅ Separate dev and prod Dockerfiles if configs differ significantly
2. ✅ Use `.dockerignore` to exclude node_modules, .git, etc.
3. ✅ Multi-stage builds for smaller images
4. ✅ Health checks for all services
5. ✅ Use Docker networks for service isolation

### CSS & Styling
1. ✅ Always include PostCSS config when using Tailwind
2. ✅ Verify CSS processing in production builds
3. ✅ Use shadcn/ui for production-ready components
4. ✅ Test responsive design on multiple screen sizes
5. ✅ Avoid inline styles; use Tailwind classes

---

## Debugging Checklist for Future Issues

### OAuth Not Working
- [ ] Check both public and internal URLs are correct
- [ ] Verify OAuth provider configuration (redirect URIs, scopes)
- [ ] Test callback endpoint directly with curl
- [ ] Check Docker network connectivity between services
- [ ] Validate JWT tokens using jwt.io
- [ ] Check browser Network tab for failed requests
- [ ] Review container logs for both auth server and client

### Styles Not Loading
- [ ] Verify `postcss.config.js` exists
- [ ] Check `tailwind.config.ts` has correct content paths
- [ ] Ensure all Tailwind plugins are in package.json
- [ ] Check CSS file size (should be >15KB)
- [ ] View page source to verify CSS link tag exists
- [ ] Test CSS URL directly in browser
- [ ] Check for CSS processing errors in build logs

### React Hydration Errors
- [ ] Check for `window`/`localStorage` access in component body
- [ ] Use mounting guard pattern for client-only components
- [ ] Ensure consistent rendering between server and client
- [ ] Check for date/time rendering (timezone issues)
- [ ] Review useEffect dependencies
- [ ] Test with React DevTools Profiler

### Container Issues
- [ ] Check container logs: `docker logs <container-name>`
- [ ] Verify environment variables: `docker exec <container> env`
- [ ] Test internal connectivity: `docker exec <container> wget <url>`
- [ ] Check network configuration: `docker network inspect <network>`
- [ ] Verify file permissions and ownership
- [ ] Check disk space: `docker system df`

---

## Performance Optimizations Applied

1. **Code Splitting**: Next.js App Router automatically splits by route
2. **Image Optimization**: Use next/image for automatic optimization
3. **Lazy Loading**: Components loaded on-demand using dynamic imports
4. **CSS Minimization**: PostCSS + Tailwind purges unused styles
5. **Caching**: Static assets cached with long TTL

---

## Security Measures Implemented

1. **HTTP-Only Cookies**: Session tokens not accessible to JavaScript
2. **CSRF Protection**: NextAuth.js handles CSRF tokens automatically
3. **JWT Validation**: All tokens verified with JWKS endpoint
4. **Environment Variables**: Secrets not committed to repo
5. **CORS Configuration**: Strict origin policies

---

## Testing Strategy

### Unit Tests
- Component rendering
- Utility functions
- API client methods

### Integration Tests
- OAuth flow end-to-end
- API authentication
- Session management

### E2E Tests
- User login flow
- Dashboard navigation
- Job submission

---

## Key Takeaways

1. **Use battle-tested libraries** instead of rolling your own auth
2. **Docker networking requires separate URLs** for internal and external access
3. **Tailwind requires proper PostCSS setup** in production builds
4. **React hydration is fragile** - avoid browser APIs during SSR
5. **Test production builds locally** before deploying
6. **Document environment variables** clearly
7. **Keep dependencies updated** to avoid security issues
8. **Use TypeScript** for better error catching
9. **Monitor build sizes** to catch CSS processing failures
10. **Log everything** during development for easier debugging
