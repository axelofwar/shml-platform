#!/bin/bash
# =============================================================================
# SFML → SHML Platform Migration Script
# =============================================================================
# This script migrates all references from 'sfml' to 'shml' across the platform.
#
# What it does:
# 1. Stops all running services
# 2. Updates Tailscale hostname
# 3. Regenerates TLS certificates
# 4. Updates all config files, scripts, and documentation
# 5. Updates FusionAuth OAuth redirect URIs
# 6. Rebuilds necessary Docker images
# 7. Restarts services
#
# Usage:
#   ./scripts/migrate_sfml_to_shml.sh [--dry-run] [--skip-tailscale] [--skip-services]
#
# Options:
#   --dry-run         Show what would be changed without making changes
#   --skip-tailscale  Skip Tailscale hostname change (if already done)
#   --skip-services   Skip stopping/starting services
#   --force           Skip confirmation prompts
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
OLD_NAME="sfml"
NEW_NAME="shml"
OLD_HOSTNAME="shml-platform"
NEW_HOSTNAME="shml-platform"
OLD_DOMAIN="shml-platform.tail38b60a.ts.net"
NEW_DOMAIN="shml-platform.tail38b60a.ts.net"

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Flags
DRY_RUN=false
SKIP_TAILSCALE=false
SKIP_SERVICES=false
FORCE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-tailscale)
            SKIP_TAILSCALE=true
            shift
            ;;
        --skip-services)
            SKIP_SERVICES=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo ""
    echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}"
}

# Confirmation prompt
confirm() {
    if [ "$FORCE" = true ]; then
        return 0
    fi
    read -p "$1 [y/N] " response
    case "$response" in
        [yY][eE][sS]|[yY])
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# Backup function
backup_file() {
    local file="$1"
    if [ -f "$file" ]; then
        cp "$file" "${file}.bak.$(date +%Y%m%d_%H%M%S)"
    fi
}

# =============================================================================
# Pre-flight checks
# =============================================================================
preflight_checks() {
    log_step "Pre-flight Checks"

    # Check we're in the right directory
    if [ ! -f "$PROJECT_ROOT/docker-compose.infra.yml" ]; then
        log_error "Must run from shml-platform project root"
        exit 1
    fi

    # Check for required tools
    for cmd in tailscale docker sed grep find; do
        if ! command -v $cmd &> /dev/null; then
            log_error "Required command not found: $cmd"
            exit 1
        fi
    done

    # Check Tailscale is running
    if ! tailscale status &> /dev/null; then
        log_error "Tailscale is not running"
        exit 1
    fi

    log_success "All pre-flight checks passed"
}

# =============================================================================
# Show migration plan
# =============================================================================
show_migration_plan() {
    log_step "Migration Plan: $OLD_NAME → $NEW_NAME"

    echo ""
    echo "This script will perform the following changes:"
    echo ""
    echo "  1. Stop all running Docker services"
    echo "  2. Change Tailscale hostname: $OLD_HOSTNAME → $NEW_HOSTNAME"
    echo "  3. Regenerate TLS certificates for: $NEW_DOMAIN"
    echo "  4. Update configuration files:"

    # Count files that will be modified (case-insensitive)
    local file_count=$(find "$PROJECT_ROOT" -type f \
        \( -name "*.yml" -o -name "*.yaml" -o -name "*.sh" -o -name "*.json" \
           -o -name "*.md" -o -name "*.py" -o -name "*.env" -o -name "*.env.*" \
           -o -name ".env*" -o -name "*.txt" -o -name "*.conf" -o -name "*.lua" \) \
        -not -path "*/archived/*" \
        -not -path "*/tests/venv/*" \
        -not -path "*/.git/*" \
        -not -path "*/node_modules/*" \
        -exec grep -li "$OLD_NAME" {} \; 2>/dev/null | wc -l)

    echo "     - $file_count files containing '$OLD_NAME' references"
    echo ""
    echo "  5. Update FusionAuth OAuth configurations"
    echo "  6. Rebuild Docker images (role-auth)"
    echo "  7. Rename TLS certificate files"
    echo "  8. Restart all services"
    echo ""

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}DRY RUN MODE: No changes will be made${NC}"
        echo ""
    fi
}

# =============================================================================
# Stop services
# =============================================================================
stop_services() {
    if [ "$SKIP_SERVICES" = true ]; then
        log_warning "Skipping service stop (--skip-services)"
        return
    fi

    log_step "Stopping Services"

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would stop all Docker services"
        return
    fi

    cd "$PROJECT_ROOT"

    # Stop all compose stacks
    log_info "Stopping infrastructure services..."
    docker compose -f docker-compose.infra.yml down --remove-orphans 2>/dev/null || true

    log_info "Stopping MLflow services..."
    docker compose -f mlflow-server/docker-compose.yml down --remove-orphans 2>/dev/null || true

    log_info "Stopping Ray services..."
    docker compose -f ray_compute/docker-compose.yml down --remove-orphans 2>/dev/null || true

    log_success "All services stopped"
}

# =============================================================================
# Update Tailscale hostname
# =============================================================================
update_tailscale() {
    if [ "$SKIP_TAILSCALE" = true ]; then
        log_warning "Skipping Tailscale hostname change (--skip-tailscale)"
        return
    fi

    log_step "Updating Tailscale Hostname"

    local current_hostname=$(tailscale status --json | jq -r '.Self.HostName')
    log_info "Current hostname: $current_hostname"

    if [ "$current_hostname" = "$NEW_HOSTNAME" ]; then
        log_success "Hostname already set to $NEW_HOSTNAME"
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would change hostname from $current_hostname to $NEW_HOSTNAME"
        return
    fi

    log_info "Changing hostname to: $NEW_HOSTNAME"
    sudo tailscale set --hostname="$NEW_HOSTNAME"

    # Wait for DNS propagation
    log_info "Waiting for DNS propagation (10 seconds)..."
    sleep 10

    # Verify
    local new_dns=$(tailscale status --json | jq -r '.Self.DNSName' | sed 's/\.$//')
    if [ "$new_dns" = "$NEW_DOMAIN" ]; then
        log_success "Hostname changed successfully: $new_dns"
    else
        log_warning "DNS name is: $new_dns (expected: $NEW_DOMAIN)"
    fi
}

# =============================================================================
# Regenerate TLS certificates
# =============================================================================
regenerate_certs() {
    log_step "Regenerating TLS Certificates"

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would regenerate TLS certificates for $NEW_DOMAIN"
        return
    fi

    cd "$PROJECT_ROOT/secrets"

    # Backup old certs
    if [ -f "${OLD_DOMAIN}.crt" ]; then
        log_info "Backing up old certificates..."
        backup_file "${OLD_DOMAIN}.crt"
        backup_file "${OLD_DOMAIN}.key"
    fi

    # Generate new certs
    log_info "Generating new certificates for $NEW_DOMAIN..."
    if tailscale cert "$NEW_DOMAIN"; then
        log_success "Certificates generated successfully"

        # Verify files exist
        if [ -f "${NEW_DOMAIN}.crt" ] && [ -f "${NEW_DOMAIN}.key" ]; then
            log_success "Certificate files verified: ${NEW_DOMAIN}.crt, ${NEW_DOMAIN}.key"
        else
            log_error "Certificate files not found!"
            exit 1
        fi
    else
        log_error "Failed to generate certificates"
        exit 1
    fi
}

# =============================================================================
# Update configuration files
# =============================================================================
update_config_files() {
    log_step "Updating Configuration Files"

    cd "$PROJECT_ROOT"

    # Find all files to update (excluding archived, venv, git, etc.)
    local files=$(find . -type f \
        \( -name "*.yml" -o -name "*.yaml" -o -name "*.sh" -o -name "*.json" \
           -o -name "*.md" -o -name "*.py" -o -name "*.env" -o -name "*.env.*" \
           -o -name ".env*" -o -name "*.txt" -o -name "*.conf" -o -name "*.lua" \
           -o -name "*.service" -o -name "Dockerfile" \) \
        -not -path "*/archived/*" \
        -not -path "*/tests/venv/*" \
        -not -path "*/.git/*" \
        -not -path "*/node_modules/*" \
        -not -name "migrate_sfml_to_shml.sh" \
        2>/dev/null)

    local updated_count=0
    local file_list=""

    for file in $files; do
        # Case-insensitive search to catch SFML, sfml, Sfml, etc.
        if grep -qi "$OLD_NAME" "$file" 2>/dev/null; then
            file_list="$file_list\n  - $file"

            if [ "$DRY_RUN" = true ]; then
                # Show what would change (case-insensitive count)
                local matches=$(grep -ci "$OLD_NAME" "$file" 2>/dev/null || echo "0")
                log_info "[DRY RUN] Would update $file ($matches occurrences)"
            else
                # Backup and update
                backup_file "$file"

                # Replace all variations
                sed -i "s/${OLD_HOSTNAME}/${NEW_HOSTNAME}/g" "$file"
                sed -i "s/${OLD_DOMAIN}/${NEW_DOMAIN}/g" "$file"
                sed -i "s/${OLD_NAME}-platform/${NEW_NAME}-platform/g" "$file"
                sed -i "s/SFML Platform/SHML Platform/g" "$file"
                sed -i "s/SFML/SHML/g" "$file"

                log_info "Updated: $file"
            fi
            updated_count=$((updated_count + 1))
        fi
    done

    if [ "$DRY_RUN" = true ]; then
        echo -e "\nFiles that would be updated:$file_list"
    fi

    log_success "Processed $updated_count files"
}

# =============================================================================
# Update FusionAuth configuration
# =============================================================================
update_fusionauth() {
    log_step "Updating FusionAuth OAuth Configuration"

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would update FusionAuth OAuth redirect URIs"
        log_info "  - Old: https://${OLD_DOMAIN}/oauth2-proxy/callback"
        log_info "  - New: https://${NEW_DOMAIN}/oauth2-proxy/callback"
        return
    fi

    # Source environment for API key
    if [ -f "$PROJECT_ROOT/.env" ]; then
        source "$PROJECT_ROOT/.env"
    fi

    if [ -z "${FUSIONAUTH_API_KEY:-}" ]; then
        log_warning "FUSIONAUTH_API_KEY not set - manual FusionAuth update may be required"
        log_info "After services start, update OAuth redirect URIs in FusionAuth admin:"
        log_info "  1. Go to https://${NEW_DOMAIN}:9011/admin/"
        log_info "  2. Navigate to Applications → OAuth2-Proxy"
        log_info "  3. Update Authorized redirect URLs to use ${NEW_DOMAIN}"
        return
    fi

    log_info "FusionAuth API update will be performed after services restart"
}

# =============================================================================
# Rebuild Docker images
# =============================================================================
rebuild_images() {
    log_step "Rebuilding Docker Images"

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would rebuild role-auth image as shml-platform/role-auth"
        return
    fi

    cd "$PROJECT_ROOT"

    # Rebuild role-auth with new name
    log_info "Building role-auth image..."
    docker build -t "${NEW_NAME}-platform/role-auth:latest" -f scripts/role-auth/Dockerfile scripts/role-auth/

    log_success "Docker images rebuilt"
}

# =============================================================================
# Update .env file with new domain
# =============================================================================
update_env_file() {
    log_step "Updating .env File"

    local env_file="$PROJECT_ROOT/.env"

    if [ ! -f "$env_file" ]; then
        log_warning ".env file not found"
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would update PUBLIC_DOMAIN in .env"
        return
    fi

    backup_file "$env_file"

    # Update PUBLIC_DOMAIN
    sed -i "s/PUBLIC_DOMAIN=${OLD_DOMAIN}/PUBLIC_DOMAIN=${NEW_DOMAIN}/g" "$env_file"

    log_success ".env file updated"
}

# =============================================================================
# Start services
# =============================================================================
start_services() {
    if [ "$SKIP_SERVICES" = true ]; then
        log_warning "Skipping service start (--skip-services)"
        return
    fi

    log_step "Starting Services"

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would start all Docker services"
        return
    fi

    cd "$PROJECT_ROOT"

    log_info "Starting infrastructure services..."
    docker compose -f docker-compose.infra.yml up -d

    log_info "Waiting for infrastructure to be ready (30 seconds)..."
    sleep 30

    log_info "Starting MLflow services..."
    docker compose -f mlflow-server/docker-compose.yml up -d

    log_info "Starting Ray services..."
    docker compose -f ray_compute/docker-compose.yml up -d

    log_success "All services started"
}

# =============================================================================
# Post-migration verification
# =============================================================================
verify_migration() {
    log_step "Verifying Migration"

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would verify migration"
        return
    fi

    local errors=0

    # Check Tailscale hostname
    local current_dns=$(tailscale status --json | jq -r '.Self.DNSName' | sed 's/\.$//')
    if [ "$current_dns" = "$NEW_DOMAIN" ]; then
        log_success "✓ Tailscale DNS: $current_dns"
    else
        log_error "✗ Tailscale DNS mismatch: $current_dns (expected: $NEW_DOMAIN)"
        ((errors++))
    fi

    # Check TLS certificates exist
    if [ -f "$PROJECT_ROOT/secrets/${NEW_DOMAIN}.crt" ]; then
        log_success "✓ TLS certificate exists"
    else
        log_error "✗ TLS certificate not found"
        ((errors++))
    fi

    # Check for remaining old references
    local remaining=$(grep -r "$OLD_DOMAIN" "$PROJECT_ROOT" \
        --include="*.yml" --include="*.yaml" --include="*.sh" --include="*.json" \
        --include="*.md" --include="*.py" --include="*.env" --include="*.env.*" \
        2>/dev/null | grep -v "archived/" | grep -v "tests/venv/" | grep -v ".bak" | wc -l)

    if [ "$remaining" -eq 0 ]; then
        log_success "✓ No remaining references to $OLD_DOMAIN"
    else
        log_warning "⚠ Found $remaining remaining references to $OLD_DOMAIN"
        log_info "Run: grep -r '$OLD_DOMAIN' . --include='*.yml' | grep -v archived"
    fi

    # Check services are running
    if [ "$SKIP_SERVICES" = false ]; then
        local running=$(docker ps --format '{{.Names}}' | wc -l)
        log_info "Running containers: $running"
    fi

    if [ $errors -eq 0 ]; then
        log_success "Migration verification complete!"
    else
        log_error "Migration completed with $errors errors"
    fi
}

# =============================================================================
# Print summary
# =============================================================================
print_summary() {
    log_step "Migration Summary"

    echo ""
    echo "The platform has been migrated from '$OLD_NAME' to '$NEW_NAME'"
    echo ""
    echo "New URLs:"
    echo "  • Landing Page:    https://${NEW_DOMAIN}/"
    echo "  • MLflow:          https://${NEW_DOMAIN}/mlflow/"
    echo "  • Ray Dashboard:   https://${NEW_DOMAIN}/ray/"
    echo "  • Grafana:         https://${NEW_DOMAIN}/grafana/"
    echo "  • Dozzle (Logs):   https://${NEW_DOMAIN}/logs/"
    echo "  • FusionAuth:      https://${NEW_DOMAIN}:9011/admin/"
    echo ""
    echo "Next steps:"
    echo "  1. Test all services at the new URLs"
    echo "  2. Update any external integrations (Google OAuth, GitHub webhooks)"
    echo "  3. Update bookmarks and documentation"
    echo "  4. Consider renaming the GitHub repository"
    echo "  5. Consider renaming the local directory"
    echo ""

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}This was a DRY RUN. No changes were made.${NC}"
        echo "Run without --dry-run to perform the actual migration."
    fi
}

# =============================================================================
# Main execution
# =============================================================================
main() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║           SFML → SHML Platform Migration Script              ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    preflight_checks
    show_migration_plan

    if [ "$DRY_RUN" = false ]; then
        if ! confirm "Proceed with migration?"; then
            log_info "Migration cancelled"
            exit 0
        fi
    fi

    stop_services
    update_tailscale
    regenerate_certs
    update_env_file
    update_config_files
    rebuild_images
    start_services
    update_fusionauth
    verify_migration
    print_summary

    log_success "Migration script completed!"
}

# Run main
main "$@"
