# MLflow Server Documentation

Complete documentation for MLflow tracking server deployment, configuration, and usage.

## 📚 Documentation Overview

### 🚀 Getting Started

1. **[QUICK_START.md](QUICK_START.md)** - Complete setup walkthrough (start here!)
   - First-time deployment
   - Basic configuration
   - Testing and verification
   - Connecting from client machines

2. **[API_USAGE_GUIDE.md](API_USAGE_GUIDE.md)** - Python client examples
   - Logging to each experiment type
   - Dataset registry usage
   - Model registry operations
   - Schema enforcement details
   - Complete workflow examples

### 🏗️ Architecture & Deployment

3. **[DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md)** - System architecture
   - Component overview
   - Data persistence
   - Network configuration
   - Service dependencies

4. **[REMOTE_CLIENT_SETUP.md](REMOTE_CLIENT_SETUP.md)** - Remote machine setup
   - Training machine configuration
   - Tailscale VPN setup
   - Environment configuration
   - Connection testing

### 🔒 Security & Configuration

5. **[SECURITY.md](SECURITY.md)** - Security best practices
   - Secret management
   - Access control
   - Git safety
   - Network security

6. **[LOCAL_CONFIG.md](LOCAL_CONFIG.md)** - Local development
   - Development environment setup
   - Testing configuration
   - Troubleshooting local issues

7. **[GIT_SETUP.md](GIT_SETUP.md)** - Git repository configuration
   - Initial setup
   - .gitignore configuration
   - Safe commit practices

### 🛠️ Troubleshooting & Maintenance

8. **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Common issues and solutions
   - Container problems
   - Connection issues
   - Database errors
   - Performance tuning
   - Backup failures

---

## 🎯 Quick Reference by Task

### I want to...

**Deploy a new server**
→ [QUICK_START.md](QUICK_START.md)

**Connect from Python**
→ [API_USAGE_GUIDE.md](API_USAGE_GUIDE.md) sections 1-2

**Log datasets**
→ [API_USAGE_GUIDE.md](API_USAGE_GUIDE.md) - Dataset Registry section

**Register models**
→ [API_USAGE_GUIDE.md](API_USAGE_GUIDE.md) - Model Registry section

**Setup remote machine**
→ [REMOTE_CLIENT_SETUP.md](REMOTE_CLIENT_SETUP.md)

**Understand architecture**
→ [DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md)

**Fix connection issues**
→ [TROUBLESHOOTING.md](TROUBLESHOOTING.md) sections 3 & 9

**Secure my deployment**
→ [SECURITY.md](SECURITY.md)

**Configure Tailscale VPN**
→ [REMOTE_CLIENT_SETUP.md](REMOTE_CLIENT_SETUP.md) + run `./scripts/ensure_tailscale.sh`

---

## 📖 Documentation Structure

```
docs/
├── README.md                    # This file - Documentation index
│
├── Quick Start & Usage
│   ├── QUICK_START.md          # Complete setup guide
│   └── API_USAGE_GUIDE.md      # Python client examples
│
├── Architecture & Deployment
│   ├── DEPLOYMENT_SUMMARY.md   # System overview
│   └── REMOTE_CLIENT_SETUP.md  # Client configuration
│
├── Security & Configuration
│   ├── SECURITY.md             # Security practices
│   ├── LOCAL_CONFIG.md         # Local development
│   └── GIT_SETUP.md            # Git configuration
│
└── Maintenance
    └── TROUBLESHOOTING.md      # Issues & solutions
```

---

## 🔧 Related Resources

### Scripts
See [../scripts/README.md](../scripts/README.md) for:
- Deployment scripts
- Management tools
- Diagnostic utilities
- Backup procedures

### Configuration
- `.env.example` - Environment variable template
- `docker-compose.yml` - Service definitions
- `config/` - Configuration templates

### Legacy Documentation
Additional resources in `mlflow_server/docs/`:
- Database access guides
- Backup retention policies
- Performance tuning
- Migration guides

---

## 💡 Tips

### For New Users
1. Start with [QUICK_START.md](QUICK_START.md)
2. Run `./scripts/deploy.sh`
3. Follow [API_USAGE_GUIDE.md](API_USAGE_GUIDE.md) examples
4. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) if issues arise

### For Administrators
1. Review [SECURITY.md](SECURITY.md)
2. Understand [DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md)
3. Configure backups (see `docker-compose.yml`)
4. Setup monitoring (Grafana at :3000)

### For Remote Users
1. Install Tailscale VPN
2. Follow [REMOTE_CLIENT_SETUP.md](REMOTE_CLIENT_SETUP.md)
3. Use examples from [API_USAGE_GUIDE.md](API_USAGE_GUIDE.md)
4. Run diagnostics with `./scripts/diagnose_remote_connection.sh`

---

## 🆘 Getting Help

**Interactive help:**
```bash
./scripts/mlflow-admin.sh  # Menu with 15 options
```

**Quick diagnostics:**
```bash
./scripts/check_status.sh        # Service health
./scripts/access_info.sh         # Connection info
docker compose logs -f mlflow    # Live logs
```

**Common issues:**
See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

**Questions or improvements?** Check [SECURITY.md](SECURITY.md) for contributing guidelines.
