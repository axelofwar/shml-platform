#!/bin/bash
# MLflow Server Management - All-in-One Helper Script
# Handles docker permissions automatically

set -e
cd /home/axelofwar/Desktop/Projects/mlflow-server

# Ensure we're in docker group
if ! groups | grep -q docker; then
    exec sg docker "$0" "$@"
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

show_menu() {
    echo ""
    echo "╔════════════════════════════════════════════════════════╗"
    echo "║       MLflow Server Management Console                ║"
    echo "╚════════════════════════════════════════════════════════╝"
    echo ""
    echo "  ${BLUE}Status & Info:${NC}"
    echo "    1) Check status"
    echo "    2) View logs (all services)"
    echo "    3) View MLflow logs only"
    echo "    4) Test persistence"
    echo ""
    echo "  ${GREEN}Operations:${NC}"
    echo "    5) Start all services"
    echo "    6) Stop all services"
    echo "    7) Restart all services"
    echo "    8) Restart MLflow only"
    echo ""
    echo "  ${YELLOW}Maintenance:${NC}"
    echo "    9) Rebuild MLflow container"
    echo "   10) Clear Redis cache"
    echo "   11) Database shell (psql)"
    echo "   12) Backup database"
    echo ""
    echo "  ${RED}Diagnostics:${NC}"
    echo "   13) Diagnose experiment IDs"
    echo "   14) Check database connections"
    echo "   15) Test all endpoints"
    echo ""
    echo "    0) Exit"
    echo ""
    echo -n "Select option: "
}

check_status() {
    echo -e "\n${BLUE}📊 MLflow Server Status${NC}\n"
    docker compose ps
    echo ""
    echo -e "${BLUE}🏥 Health Check:${NC}"
    HEALTH=$(curl -s http://localhost:8080/health)
    if [ "$HEALTH" == "OK" ]; then
        echo -e "${GREEN}✅ $HEALTH${NC}"
    else
        echo -e "${RED}❌ Server not responding${NC}"
    fi
    echo ""
    echo -e "${BLUE}📊 Version:${NC} $(curl -s http://localhost:8080/version)"
    echo ""
    echo -e "${BLUE}🧪 Experiments:${NC}"
    curl -s -X POST http://localhost:8080/api/2.0/mlflow/experiments/search \
      -H "Content-Type: application/json" -d '{"max_results": 100}' | \
      python3 -c "import sys,json; exps=json.load(sys.stdin)['experiments']; print(f'  Total: {len(exps)}'); [print(f'  [{exp[\"experiment_id\"]}] {exp[\"name\"]}') for exp in exps]"
}

view_logs() {
    echo -e "\n${BLUE}📋 Service Logs (Ctrl+C to exit)${NC}\n"
    docker compose logs -f --tail=50
}

view_mlflow_logs() {
    echo -e "\n${BLUE}📋 MLflow Logs (Ctrl+C to exit)${NC}\n"
    docker logs mlflow-server -f --tail=100
}

test_persistence() {
    echo -e "\n${BLUE}🔄 Testing Persistence...${NC}\n"
    echo "Restarting MLflow..."
    docker compose restart mlflow
    echo "Waiting for startup..."
    sleep 20
    echo ""
    echo "Testing experiments..."
    curl -s -X POST http://localhost:8080/api/2.0/mlflow/experiments/search \
      -H "Content-Type: application/json" -d '{"max_results": 100}' | \
      python3 -c "import sys,json; exps=json.load(sys.stdin)['experiments']; print(f'${GREEN}✅ {len(exps)} experiments persisted!${NC}'); [print(f'  [{exp[\"experiment_id\"]}] {exp[\"name\"]}') for exp in exps]"
}

start_services() {
    echo -e "\n${GREEN}🚀 Starting all services...${NC}\n"
    docker compose up -d
    echo ""
    echo -e "${GREEN}✅ Services started${NC}"
    sleep 10
    docker compose ps
}

stop_services() {
    echo -e "\n${YELLOW}🛑 Stopping all services...${NC}\n"
    docker compose down
    echo -e "${GREEN}✅ Services stopped${NC}"
}

restart_services() {
    echo -e "\n${YELLOW}🔄 Restarting all services...${NC}\n"
    docker compose restart
    echo -e "${GREEN}✅ Services restarted${NC}"
    sleep 10
    docker compose ps
}

restart_mlflow() {
    echo -e "\n${YELLOW}🔄 Restarting MLflow...${NC}\n"
    docker compose restart mlflow
    echo "Waiting for startup..."
    sleep 15
    echo -e "${GREEN}✅ MLflow restarted${NC}"
}

rebuild_mlflow() {
    echo -e "\n${YELLOW}🔨 Rebuilding MLflow container...${NC}\n"
    docker compose build mlflow
    echo ""
    echo "Starting MLflow..."
    docker compose up -d mlflow
    echo "Waiting for startup..."
    sleep 20
    docker logs mlflow-server --tail 30
    echo ""
    echo -e "${GREEN}✅ MLflow rebuilt and started${NC}"
}

clear_cache() {
    echo -e "\n${YELLOW}🗑️  Clearing Redis cache...${NC}\n"
    docker exec mlflow-redis redis-cli FLUSHALL
    echo -e "${GREEN}✅ Cache cleared${NC}"
}

database_shell() {
    echo -e "\n${BLUE}🗄️  PostgreSQL Shell (type \\q to exit)${NC}\n"
    docker exec -it mlflow-postgres psql -U mlflow -d mlflow_db
}

backup_database() {
    echo -e "\n${BLUE}💾 Backing up database...${NC}\n"
    BACKUP_FILE="backups/postgres/manual_backup_$(date +%Y%m%d_%H%M%S).sql"
    mkdir -p backups/postgres
    docker exec mlflow-postgres pg_dump -U mlflow mlflow_db > "$BACKUP_FILE"
    echo -e "${GREEN}✅ Database backed up to: $BACKUP_FILE${NC}"
    ls -lh "$BACKUP_FILE"
}

diagnose_experiments() {
    echo -e "\n${BLUE}🔍 Diagnosing Experiment IDs...${NC}\n"
    docker exec mlflow-postgres psql -U mlflow -d mlflow_db -c \
      "SELECT experiment_id, name, lifecycle_stage FROM experiments ORDER BY experiment_id;"
    echo ""
    echo "Checking for out-of-range IDs..."
    docker exec mlflow-postgres psql -U mlflow -d mlflow_db -c \
      "SELECT experiment_id FROM experiments WHERE CAST(experiment_id AS BIGINT) > 2147483647;"
}

check_db_connections() {
    echo -e "\n${BLUE}🔌 Checking Database Connections...${NC}\n"
    docker exec mlflow-postgres psql -U mlflow -d mlflow_db -c \
      "SELECT datname, numbackends, xact_commit, xact_rollback FROM pg_stat_database WHERE datname='mlflow_db';"
}

test_endpoints() {
    echo -e "\n${BLUE}🧪 Testing All Endpoints...${NC}\n"

    echo "1. Health:"
    curl -s http://localhost:8080/health && echo "" || echo -e "${RED}❌ Failed${NC}"

    echo "2. Version:"
    curl -s http://localhost:8080/version && echo "" || echo -e "${RED}❌ Failed${NC}"

    echo "3. Experiments:"
    curl -s -X POST http://localhost:8080/api/2.0/mlflow/experiments/search -H "Content-Type: application/json" -d '{"max_results": 10}' | python3 -c "import sys,json; print(f'${GREEN}✅ {len(json.load(sys.stdin)[\"experiments\"])} found${NC}')" || echo -e "${RED}❌ Failed${NC}"

    echo "4. Registered Models:"
    curl -s -X GET http://localhost:8080/api/2.0/mlflow/registered-models/search | python3 -c "import sys,json; print(f'${GREEN}✅ API working${NC}')" || echo -e "${RED}❌ Failed${NC}"

    echo ""
    echo -e "${GREEN}✅ All endpoints tested${NC}"
}

# Main loop
while true; do
    show_menu
    read choice

    case $choice in
        1) check_status ;;
        2) view_logs ;;
        3) view_mlflow_logs ;;
        4) test_persistence ;;
        5) start_services ;;
        6) stop_services ;;
        7) restart_services ;;
        8) restart_mlflow ;;
        9) rebuild_mlflow ;;
        10) clear_cache ;;
        11) database_shell ;;
        12) backup_database ;;
        13) diagnose_experiments ;;
        14) check_db_connections ;;
        15) test_endpoints ;;
        0) echo "Goodbye!"; exit 0 ;;
        *) echo -e "${RED}Invalid option${NC}" ;;
    esac

    echo ""
    read -p "Press Enter to continue..."
done
