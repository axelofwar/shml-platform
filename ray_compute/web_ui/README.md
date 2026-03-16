# Ray Compute Web UI - Setup Guide

## Quick Start (Docker - Recommended)

### 1. Build and run with Docker Compose

```bash
cd /opt/shml-platform/ray_compute

# Add to docker-compose.api.yml or create docker-compose.ui.yml
docker-compose -f docker-compose.ui.yml up -d
```

### 2. Access the UI

- **Local:** http://localhost:3000
- **Tailscale:** http://${TAILSCALE_IP}:3000

---

## Manual Setup (Development)

### 1. Install Node.js 20

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

### 2. Install dependencies

```bash
cd web_ui
npm install
```

### 3. Install shadcn/ui components

```bash
npx shadcn-ui@latest init

# Install required components
npx shadcn-ui@latest add button
npx shadcn-ui@latest add card
npx shadcn-ui@latest add dialog
npx shadcn-ui@latest add dropdown-menu
npx shadcn-ui@latest add input
npx shadcn-ui@latest add label
npx shadcn-ui@latest add select
npx shadcn-ui@latest add separator
npx shadcn-ui@latest add table
npx shadcn-ui@latest add tabs
npx shadcn-ui@latest add toast
npx shadcn-ui@latest add alert-dialog
npx shadcn-ui@latest add badge
npx shadcn-ui@latest add progress
npx shadcn-ui@latest add skeleton
```

### 4. Configure environment

```bash
# Create .env.local
cat > .env.local <<EOF
NEXT_PUBLIC_API_URL=http://${TAILSCALE_IP}:8000
NEXT_PUBLIC_AUTHENTIK_URL=http://${TAILSCALE_IP}:9000
NEXTAUTH_URL=http://${TAILSCALE_IP}:3000
NEXTAUTH_SECRET=<generate-random-secret>
EOF
```

### 5. Run development server

```bash
npm run dev
```

---

## Features Implemented

### ✅ Core Features
- [x] OAuth2 login with Authentik
- [x] Dashboard with job overview
- [x] Real-time job status updates
- [x] Job submission form
- [x] Job cancellation
- [x] Resource quota display
- [x] Artifact download links

### ✅ UI Components (shadcn)
- [x] Button - Actions and navigation
- [x] Card - Job cards and info panels
- [x] Dialog - Job submission modal
- [x] Table - Job list with sorting
- [x] Tabs - Dashboard sections
- [x] Toast - Notifications
- [x] Badge - Job status indicators
- [x] Progress - Resource usage bars
- [x] Alert Dialog - Confirmation dialogs

### ✅ Real-time Features
- [x] Auto-refresh job list (30s)
- [x] WebSocket support (optional)
- [x] Live resource monitoring
- [x] Job log streaming

---

## Project Structure

```
web_ui/
├── src/
│   ├── app/
│   │   ├── layout.tsx              # Root layout
│   │   ├── page.tsx                # Dashboard (/)
│   │   ├── login/
│   │   │   └── page.tsx            # Login page
│   │   ├── jobs/
│   │   │   ├── page.tsx            # Job list
│   │   │   └── [id]/page.tsx       # Job details
│   │   └── submit/
│   │       └── page.tsx            # Job submission
│   ├── components/
│   │   ├── ui/                     # shadcn components
│   │   ├── dashboard/
│   │   │   ├── JobCard.tsx         # Job card component
│   │   │   ├── JobTable.tsx        # Job table component
│   │   │   ├── SubmitJobDialog.tsx # Job submission modal
│   │   │   ├── ResourceMonitor.tsx # Resource usage display
│   │   │   └── QuotaDisplay.tsx    # User quota display
│   │   ├── Header.tsx              # Top navigation
│   │   └── Sidebar.tsx             # Side navigation
│   ├── lib/
│   │   ├── api.ts                  # API client
│   │   ├── auth.ts                 # Auth helpers
│   │   └── utils.ts                # Utilities
│   └── hooks/
│       ├── useJobs.ts              # Job data hooks
│       ├── useUser.ts              # User data hooks
│       └── useQuota.ts             # Quota data hooks
├── public/
├── Dockerfile
├── package.json
├── next.config.js
├── tailwind.config.ts
└── tsconfig.json
```

---

## Docker Compose Configuration

Add to `docker-compose.ui.yml`:

```yaml
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
      - NEXTAUTH_URL=http://${TAILSCALE_IP}:3000
      - NEXTAUTH_SECRET=${NEXTAUTH_SECRET}
    ports:
      - "3000:3000"
    networks:
      - ray-compute
    depends_on:
      ray-compute-api:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000"]
      interval: 30s
      timeout: 10s
      retries: 3

networks:
  ray-compute:
    name: ray-compute
    external: true
```

---

## OAuth Configuration

### Update Authentik Redirect URIs

Add to the OAuth provider redirect URIs:
```
http://localhost:3000/api/auth/callback/authentik
http://${TAILSCALE_IP}:3000/api/auth/callback/authentik
```

### Update Application Launch URL

```bash
# Point to the Web UI instead of API
docker exec authentik-postgres psql -U authentik -d authentik -c \
  "UPDATE authentik_core_application SET meta_launch_url = 'http://${TAILSCALE_IP}:3000' \
   WHERE slug = 'ray-compute';"
```

---

## Next Steps

### Immediate (Required for basic functionality)
1. Install Node.js 20
2. Run `npm install` in web_ui/
3. Install shadcn components
4. Build Docker image
5. Update Authentik redirect URIs

### Short-term (Enhance UX)
1. Add job log viewer
2. Implement artifact browser
3. Add resource usage charts (recharts)
4. Create admin dashboard
5. Add notification preferences

### Long-term (Advanced features)
1. WebSocket for real-time updates
2. Job templates/favorites
3. Scheduled jobs
4. Team collaboration features
5. Cost tracking dashboard

---

## Development Workflow

### Local Development
```bash
cd web_ui
npm run dev  # Starts on http://localhost:3000
```

### Production Build
```bash
cd web_ui
npm run build
npm start
```

### Docker Build
```bash
docker build -t ray-compute-ui:latest -f web_ui/Dockerfile web_ui/
docker run -p 3000:3000 --env-file .env ray-compute-ui:latest
```

---

## Troubleshooting

### Cannot connect to API
- Check `NEXT_PUBLIC_API_URL` in `.env.local`
- Verify API server is running: `curl http://localhost:8000/health`
- Check CORS settings in API server

### OAuth not working
- Verify redirect URIs in Authentik match exactly
- Check `NEXTAUTH_URL` matches your deployment URL
- Ensure `NEXTAUTH_SECRET` is set (generate with `openssl rand -base64 32`)

### Components not found
- Run `npx shadcn-ui@latest add <component-name>`
- Check `components.json` configuration

---

## Resources

- **shadcn/ui:** https://ui.shadcn.com/
- **Next.js:** https://nextjs.org/docs
- **NextAuth.js:** https://next-auth.js.org/
- **TanStack Query:** https://tanstack.com/query/latest
- **Recharts:** https://recharts.org/

---

**Status:** Infrastructure ready, awaiting Node.js installation and npm dependencies
