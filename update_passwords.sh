#!/bin/bash
# Update all admin passwords for ML Platform services
# Usage: ./update_passwords.sh [new_password]

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get new password
if [ -z "$1" ]; then
    echo "Usage: ./update_passwords.sh <new_password>"
    echo ""
    echo "Example: ./update_passwords.sh AiSolutions2350!"
    echo ""
    echo "This will update passwords for:"
    echo "  - MLflow Grafana (admin)"
    echo "  - Ray Grafana (admin)"
    echo "  - Authentik (akadmin bootstrap)"
    exit 1
fi

NEW_PASSWORD="$1"

echo "========================================"
echo "  ML PLATFORM PASSWORD UPDATE"
echo "========================================"
echo ""
echo -e "${YELLOW}⚠  This will update all admin passwords${NC}"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "Updating passwords..."
echo ""

# Update MLflow Grafana
echo "1. MLflow Grafana..."
echo "$NEW_PASSWORD" > mlflow-server/secrets/grafana_password.txt
if docker exec mlflow-grafana grafana-cli admin reset-admin-password "$NEW_PASSWORD" > /dev/null 2>&1; then
    echo -e "   ${GREEN}✓${NC} Password updated"
    echo -e "   ${GREEN}✓${NC} Saved to mlflow-server/secrets/grafana_password.txt"
else
    echo -e "   ${YELLOW}⚠${NC}  Container update failed, but file saved"
fi
echo ""

# Update Ray Grafana
echo "2. Ray Grafana..."
if docker ps | grep -q ray-grafana; then
    if docker exec ray-grafana grafana-cli admin reset-admin-password "$NEW_PASSWORD" > /dev/null 2>&1; then
        echo -e "   ${GREEN}✓${NC} Password updated"
    else
        echo -e "   ${YELLOW}⚠${NC}  Container update failed"
    fi
else
    echo -e "   ${YELLOW}⚠${NC}  Container not running (will use password on next start)"
fi

# Update .env file for Ray Grafana
if [ -f ray_compute/.env ]; then
    if grep -q "GRAFANA_ADMIN_PASSWORD" ray_compute/.env; then
        sed -i "s/GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=$NEW_PASSWORD/" ray_compute/.env
    else
        echo "GRAFANA_ADMIN_PASSWORD=$NEW_PASSWORD" >> ray_compute/.env
    fi
    echo -e "   ${GREEN}✓${NC} Saved to ray_compute/.env"
fi
echo ""

# Update Authentik bootstrap password
echo "3. Authentik (bootstrap)..."
if [ -f ray_compute/.env ]; then
    if grep -q "AUTHENTIK_BOOTSTRAP_PASSWORD" ray_compute/.env; then
        sed -i "s/AUTHENTIK_BOOTSTRAP_PASSWORD=.*/AUTHENTIK_BOOTSTRAP_PASSWORD=$NEW_PASSWORD/" ray_compute/.env
        echo -e "   ${GREEN}✓${NC} Updated in ray_compute/.env"
    else
        echo "AUTHENTIK_BOOTSTRAP_PASSWORD=$NEW_PASSWORD" >> ray_compute/.env
        echo -e "   ${GREEN}✓${NC} Added to ray_compute/.env"
    fi
    echo -e "   ${YELLOW}⚠${NC}  Restart Authentik to apply: docker-compose -f ray_compute/docker-compose.auth.yml restart"
fi
echo ""

echo "========================================"
echo -e "${GREEN}✓ PASSWORD UPDATE COMPLETE${NC}"
echo "========================================"
echo ""
echo "New password set for all services: $NEW_PASSWORD"
echo ""
echo "Credentials are stored in:"
echo "  • mlflow-server/secrets/grafana_password.txt (MLflow Grafana)"
echo "  • ray_compute/.env (Ray Grafana & Authentik)"
echo ""
echo "Test logins:"
echo "  • MLflow Grafana: http://<YOUR_SERVER_IP>/grafana/ (admin / $NEW_PASSWORD)"
echo "  • Ray Grafana: http://<YOUR_SERVER_IP>/ray-grafana/ (admin / $NEW_PASSWORD)"
echo "  • Authentik: http://<YOUR_SERVER_IP>:9000 (akadmin / $NEW_PASSWORD)"
echo ""
