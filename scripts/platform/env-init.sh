#!/bin/bash
# =============================================================================
# env-init.sh — Dynamic Environment Initialization
# =============================================================================
# Auto-discovers network addresses and updates .env files before services start.
# Called from start_all_safe.sh during startup, or run standalone:
#
#   ./scripts/platform/env-init.sh           # Detect and update, show diff
#   ./scripts/platform/env-init.sh --dry-run # Show what would change, no writes
#   ./scripts/platform/env-init.sh --quiet   # Suppress output (for cron/systemd)
#
# Updates:
#   - .env              (LAN_IP, TAILSCALE_IP)
#   - ray_compute/.env  (TAILSCALE_IP)
#   - monitoring/homer/config.yml  (LAN IP references)
#
# IDEMPOTENT: If values haven't changed, no files are touched.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Options
DRY_RUN=false
QUIET=false
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --quiet)   QUIET=true ;;
    esac
done

# Colors (suppressed in quiet mode)
if [ "$QUIET" = false ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' CYAN='' NC=''
fi

log_info()    { [ "$QUIET" = false ] && echo -e "${CYAN}[env-init] $1${NC}" || true; }
log_success() { [ "$QUIET" = false ] && echo -e "${GREEN}[env-init] ✓ $1${NC}" || true; }
log_warn()    { [ "$QUIET" = false ] && echo -e "${YELLOW}[env-init] ⚠ $1${NC}" || true; }
log_change()  { [ "$QUIET" = false ] && echo -e "${YELLOW}[env-init] ↻ $1${NC}" || true; }

# =============================================================================
# 1. Detect LAN IP
# =============================================================================
# Strategy: find the first IPv4 address on an interface that is NOT:
#   - loopback (lo)
#   - Docker bridge (docker0, br-*)
#   - veth pair (veth*)
#   - Tailscale (tailscale*)
#   - Loopback address (127.x.x.x)
#
# Uses `ip -4 -o addr show` one-line format:
#   <idx>: <iface>    inet <addr>/<prefix> ...
#
detect_lan_ip() {
    ip -4 -o addr show 2>/dev/null | awk '
        $2 !~ /^(lo$|docker|br-|veth|tailscale)/ &&
        $4 !~ /^127\./ {
            split($4, a, "/")
            print a[1]
            exit
        }
    '
}

# =============================================================================
# 2. Detect Tailscale IP
# =============================================================================
detect_tailscale_ip() {
    if command -v tailscale &>/dev/null; then
        tailscale ip -4 2>/dev/null || echo ""
    else
        echo ""
    fi
}

# =============================================================================
# 2b. Detect public Tailscale domain (MagicDNS hostname)
# =============================================================================
detect_public_domain() {
    if command -v tailscale &>/dev/null; then
        local dns_name
        dns_name=$(tailscale status --json 2>/dev/null | jq -r '.Self.DNSName // empty' 2>/dev/null | sed 's/\.$//' || true)
        if [ -n "$dns_name" ] && [ "$dns_name" != "null" ]; then
            echo "$dns_name"
        else
            tailscale status --json 2>/dev/null | jq -r '.Self.HostName + "." + .MagicDNSSuffix' 2>/dev/null || echo ""
        fi
    else
        echo ""
    fi
}

# =============================================================================
# 3. Update a key=value pair in an env file (in-place, idempotent)
# =============================================================================
# Returns 0 if changed, 1 if unchanged
update_env_key() {
    local file="$1"
    local key="$2"
    local new_value="$3"

    if [ ! -f "$file" ]; then
        log_warn "File not found: $file (skipping $key)"
        return 1
    fi

    local current_value
    current_value=$(grep "^${key}=" "$file" 2>/dev/null | head -1 | cut -d'=' -f2- || echo "")

    if [ "$current_value" = "$new_value" ]; then
        return 1  # unchanged
    fi

    if [ "$DRY_RUN" = true ]; then
        log_change "Would update ${key} in $(basename "$file"): ${current_value} → ${new_value}"
        return 0
    fi

    if grep -q "^${key}=" "$file"; then
        # Key exists — update it
        sed -i "s|^${key}=.*|${key}=${new_value}|" "$file"
    else
        # Key missing — append it
        echo "" >> "$file"
        echo "# Auto-added by env-init.sh" >> "$file"
        echo "${key}=${new_value}" >> "$file"
    fi

    log_change "Updated ${key} in $(basename "$file"): ${current_value:-<unset>} → ${new_value}"
    return 0
}

# =============================================================================
# 4. Update Homer config IP references
# =============================================================================
update_homer_ip() {
    local homer_config="$PLATFORM_DIR/monitoring/homer/config.yml"
    local old_ip="$1"
    local new_ip="$2"

    if [ ! -f "$homer_config" ]; then
        log_warn "Homer config not found: $homer_config (skipping)"
        return
    fi

    if [ "$old_ip" = "$new_ip" ] || [ -z "$old_ip" ]; then
        return
    fi

    # Check if old IP appears in homer config
    if ! grep -q "$old_ip" "$homer_config" 2>/dev/null; then
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        local count
        count=$(grep -c "$old_ip" "$homer_config" || echo "0")
        log_change "Would update $count Homer config reference(s): ${old_ip} → ${new_ip}"
        return
    fi

    local count
    count=$(grep -c "$old_ip" "$homer_config" || echo "0")
    sed -i "s|${old_ip}|${new_ip}|g" "$homer_config"
    log_change "Updated $count Homer config reference(s): ${old_ip} → ${new_ip}"
}

# =============================================================================
# Main
# =============================================================================
main() {
    log_info "Detecting network addresses..."

    # Discover current values
    local detected_lan_ip
    local detected_tailscale_ip
    local detected_public_domain
    detected_lan_ip=$(detect_lan_ip)
    detected_tailscale_ip=$(detect_tailscale_ip)
    detected_public_domain=$(detect_public_domain)

    # Validate discoveries
    if [ -z "$detected_lan_ip" ]; then
        log_warn "Could not detect LAN IP — keeping existing value"
        detected_lan_ip=""
    else
        log_info "Detected LAN IP:       ${detected_lan_ip}"
    fi

    if [ -z "$detected_tailscale_ip" ]; then
        log_warn "Could not detect Tailscale IP (Tailscale not running?) — keeping existing value"
    else
        log_info "Detected Tailscale IP: ${detected_tailscale_ip}"
    fi

    if [ -z "$detected_public_domain" ]; then
        log_warn "Could not detect PUBLIC_DOMAIN from Tailscale — keeping existing value"
    else
        log_info "Detected PUBLIC_DOMAIN: ${detected_public_domain}"
    fi

    # Read current values from .env for change tracking (Homer needs old IP)
    local main_env="$PLATFORM_DIR/.env"
    local old_lan_ip=""
    if [ -f "$main_env" ]; then
        old_lan_ip=$(grep "^LAN_IP=" "$main_env" 2>/dev/null | cut -d'=' -f2 || echo "")
    fi

    # Track whether anything changed
    local changed=false

    # Update LAN_IP in main .env
    if [ -n "$detected_lan_ip" ]; then
        update_env_key "$main_env" "LAN_IP" "$detected_lan_ip" && changed=true || true
    fi

    # Update TAILSCALE_IP in main .env
    if [ -n "$detected_tailscale_ip" ]; then
        update_env_key "$main_env" "TAILSCALE_IP" "$detected_tailscale_ip" && changed=true || true
    fi

    # Update TAILSCALE_IP in ray_compute/.env
    local ray_env="$PLATFORM_DIR/ray_compute/.env"
    if [ -n "$detected_tailscale_ip" ]; then
        update_env_key "$ray_env" "TAILSCALE_IP" "$detected_tailscale_ip" && changed=true || true
    fi

    # Update PUBLIC_DOMAIN in main .env and ray_compute/.env
    if [ -n "$detected_public_domain" ]; then
        update_env_key "$main_env" "PUBLIC_DOMAIN" "$detected_public_domain" && changed=true || true
        update_env_key "$main_env" "FUSIONAUTH_ISSUER" "https://${detected_public_domain}" && changed=true || true
        update_env_key "$main_env" "INFISICAL_SITE_URL" "https://${detected_public_domain}/secrets" && changed=true || true
        update_env_key "$ray_env" "PUBLIC_DOMAIN" "$detected_public_domain" && changed=true || true
    fi

    # Update Homer config if LAN IP changed
    if [ -n "$detected_lan_ip" ] && [ -n "$old_lan_ip" ] && [ "$old_lan_ip" != "$detected_lan_ip" ]; then
        update_homer_ip "$old_lan_ip" "$detected_lan_ip"
        changed=true
    fi

    # Summary
    if [ "$changed" = true ]; then
        if [ "$DRY_RUN" = true ]; then
            log_info "Dry run complete — no files written"
        else
            log_success "Environment updated successfully"
        fi
    else
        log_success "All values current — no changes needed"
    fi
}

main "$@"
