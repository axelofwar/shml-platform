#!/bin/bash
# Tailscale Funnel Management Script for SFML Platform
# Manages the public HTTPS endpoint via Tailscale Funnel

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Get the public domain
get_public_domain() {
    local tailnet=$(tailscale status --json 2>/dev/null | jq -r '.MagicDNSSuffix' 2>/dev/null)
    local hostname=$(tailscale status --json 2>/dev/null | jq -r '.Self.HostName' 2>/dev/null)
    if [ -n "$tailnet" ] && [ -n "$hostname" ]; then
        echo "${hostname}.${tailnet}"
    else
        echo ""
    fi
}

# Check if funnel is enabled
check_funnel_enabled() {
    tailscale funnel status 2>&1 | grep -q "https://" && return 0 || return 1
}

start_funnel() {
    echo -e "${BLUE}Starting Tailscale Funnel...${NC}"

    local domain=$(get_public_domain)
    if [ -z "$domain" ]; then
        echo -e "${RED}✗ Could not determine Tailscale domain${NC}"
        exit 1
    fi

    echo "Public domain: https://${domain}"

    # Enable funnel - routes HTTPS 443 to local Traefik on port 80
    sudo tailscale funnel --bg 80

    if check_funnel_enabled; then
        echo -e "${GREEN}✓ Funnel started successfully${NC}"
        echo ""
        echo -e "${CYAN}Public URLs:${NC}"
        echo "  Auth:    https://${domain}/auth/"
        echo "  MLflow:  https://${domain}/mlflow/"
        echo "  Ray:     https://${domain}/ray/"
        echo "  Grafana: https://${domain}/grafana/"
        echo ""

        # Update .env with the domain
        if [ -f "$PLATFORM_DIR/.env" ]; then
            if grep -q "^PUBLIC_DOMAIN=" "$PLATFORM_DIR/.env"; then
                sed -i "s|^PUBLIC_DOMAIN=.*|PUBLIC_DOMAIN=${domain}|" "$PLATFORM_DIR/.env"
            else
                echo "" >> "$PLATFORM_DIR/.env"
                echo "# Public domain via Tailscale Funnel" >> "$PLATFORM_DIR/.env"
                echo "PUBLIC_DOMAIN=${domain}" >> "$PLATFORM_DIR/.env"
            fi
            echo -e "${GREEN}✓ Updated PUBLIC_DOMAIN in .env${NC}"
        fi
    else
        echo -e "${RED}✗ Failed to start funnel${NC}"
        exit 1
    fi
}

stop_funnel() {
    echo -e "${BLUE}Stopping Tailscale Funnel...${NC}"
    tailscale funnel --https=443 off 2>/dev/null || true
    tailscale serve reset 2>/dev/null || true
    echo -e "${GREEN}✓ Funnel stopped${NC}"
}

status_funnel() {
    echo -e "${BLUE}Tailscale Funnel Status${NC}"
    echo ""

    local domain=$(get_public_domain)
    if [ -n "$domain" ]; then
        echo -e "Domain: ${CYAN}https://${domain}${NC}"
    fi
    echo ""

    tailscale funnel status
}

install_systemd() {
    echo -e "${BLUE}Installing Tailscale Funnel systemd service...${NC}"

    if [ "$EUID" -ne 0 ]; then
        echo -e "${YELLOW}Requires sudo - prompting for password...${NC}"
        sudo cp "$SCRIPT_DIR/tailscale-funnel.service" /etc/systemd/system/
        sudo systemctl daemon-reload
        sudo systemctl enable tailscale-funnel.service
        echo -e "${GREEN}✓ Systemd service installed and enabled${NC}"
    else
        cp "$SCRIPT_DIR/tailscale-funnel.service" /etc/systemd/system/
        systemctl daemon-reload
        systemctl enable tailscale-funnel.service
        echo -e "${GREEN}✓ Systemd service installed and enabled${NC}"
    fi
}

uninstall_systemd() {
    echo -e "${BLUE}Removing Tailscale Funnel systemd service...${NC}"

    if [ "$EUID" -ne 0 ]; then
        sudo systemctl stop tailscale-funnel.service 2>/dev/null || true
        sudo systemctl disable tailscale-funnel.service 2>/dev/null || true
        sudo rm -f /etc/systemd/system/tailscale-funnel.service
        sudo systemctl daemon-reload
    else
        systemctl stop tailscale-funnel.service 2>/dev/null || true
        systemctl disable tailscale-funnel.service 2>/dev/null || true
        rm -f /etc/systemd/system/tailscale-funnel.service
        systemctl daemon-reload
    fi

    echo -e "${GREEN}✓ Systemd service removed${NC}"
}

usage() {
    echo "Usage: $0 {start|stop|status|restart|install|uninstall}"
    echo ""
    echo "Commands:"
    echo "  start     - Start Tailscale Funnel (port 443 -> Traefik)"
    echo "  stop      - Stop Tailscale Funnel"
    echo "  status    - Show Funnel status"
    echo "  restart   - Restart Funnel"
    echo "  install   - Install as systemd service (auto-start on boot)"
    echo "  uninstall - Remove systemd service"
}

case "${1:-}" in
    start)
        start_funnel
        ;;
    stop)
        stop_funnel
        ;;
    status)
        status_funnel
        ;;
    restart)
        stop_funnel
        sleep 1
        start_funnel
        ;;
    install)
        install_systemd
        ;;
    uninstall)
        uninstall_systemd
        ;;
    *)
        usage
        exit 1
        ;;
esac
