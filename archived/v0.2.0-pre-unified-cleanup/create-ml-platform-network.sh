#!/bin/bash
#
# Create ML Platform Shared Network
# Creates bridge network for MLflow + Ray Compute communication
#

set -e

NETWORK_NAME="ml-platform"
SUBNET="172.30.0.0/16"
GATEWAY="172.30.0.1"

echo "================================================"
echo "ML Platform Network Setup"
echo "================================================"
echo ""

# Check if network already exists
if docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    echo "✓ Network '$NETWORK_NAME' already exists"
    echo ""
    echo "Network details:"
    docker network inspect "$NETWORK_NAME" --format '{{range .IPAM.Config}}Subnet: {{.Subnet}} Gateway: {{.Gateway}}{{end}}'
    echo ""
    echo "Connected containers:"
    docker network inspect "$NETWORK_NAME" --format '{{range $k, $v := .Containers}}  - {{$v.Name}} ({{$v.IPv4Address}}){{println}}{{end}}'
else
    echo "Creating network '$NETWORK_NAME'..."
    docker network create \
        --driver bridge \
        --subnet "$SUBNET" \
        --gateway "$GATEWAY" \
        "$NETWORK_NAME"
    
    echo "✓ Network '$NETWORK_NAME' created successfully"
    echo ""
    echo "Network configuration:"
    echo "  Name:    $NETWORK_NAME"
    echo "  Subnet:  $SUBNET"
    echo "  Gateway: $GATEWAY"
    echo "  Driver:  bridge"
fi

echo ""
echo "================================================"
echo "Next Steps:"
echo "================================================"
echo ""
echo "1. Update docker-compose files to use this network"
echo "2. Restart services: cd mlflow-server && docker compose down && docker compose up -d"
echo "3. Restart services: cd ray_compute && docker compose -f docker-compose.api.yml down && docker compose -f docker-compose.api.yml up -d"
echo "4. Test connectivity: docker exec mlflow-server ping -c 1 ray-compute-api"
echo ""
