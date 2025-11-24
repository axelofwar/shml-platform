#!/bin/bash
#
# MLflow Server Automated Setup Script
# For: Dedicated hardware (old PC, Raspberry Pi, mini PC, etc.)
# Privacy: Maximum (local deployment, no cloud)
# Time: 20-30 minutes
#

set -e  # Exit on error

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# Banner
echo "════════════════════════════════════════════════════════════════"
echo "           MLflow Server Automated Setup"
echo "           Privacy-First Local Deployment"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
    log_error "Please run as regular user, not root. Script will prompt for sudo when needed."
    exit 1
fi

# System requirements check
log_info "Checking system requirements..."

# Check CPU cores
CPU_CORES=$(nproc)
if [ "$CPU_CORES" -lt 2 ]; then
    log_warning "Only $CPU_CORES CPU core detected. Minimum 2 cores recommended."
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    log_success "CPU: $CPU_CORES cores (Good)"
fi

# Check RAM
TOTAL_RAM=$(free -m | awk 'NR==2{printf "%.0f", $2}')
if [ "$TOTAL_RAM" -lt 2048 ]; then
    log_warning "Only ${TOTAL_RAM}MB RAM detected. Minimum 2GB recommended."
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    log_success "RAM: ${TOTAL_RAM}MB (Good)"
fi

# Check disk space
AVAILABLE_DISK=$(df -BG / | awk 'NR==2{print $4}' | sed 's/G//')
if [ "$AVAILABLE_DISK" -lt 50 ]; then
    log_warning "Only ${AVAILABLE_DISK}GB disk space available. Minimum 50GB recommended."
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    log_success "Disk: ${AVAILABLE_DISK}GB available (Good)"
fi

echo ""
log_info "System check passed! Proceeding with installation..."
echo ""

# Configuration prompts
log_info "Setup Configuration"
echo "─────────────────────────────────────────────────────────────────"

# PostgreSQL or SQLite
echo ""
echo "Backend Storage Options:"
echo "  1) PostgreSQL (Recommended - Better performance, concurrent access)"
echo "  2) SQLite (Simpler - File-based, good for single user)"
echo ""
read -p "Choose backend [1-2] (default: 1): " BACKEND_CHOICE
BACKEND_CHOICE=${BACKEND_CHOICE:-1}

# MLflow port
echo ""
read -p "MLflow UI port (default: 5000): " MLFLOW_PORT
MLFLOW_PORT=${MLFLOW_PORT:-5000}

# PostgreSQL password (if selected)
if [ "$BACKEND_CHOICE" == "1" ]; then
    echo ""
    read -sp "PostgreSQL password for mlflow user (will be created): " DB_PASSWORD
    echo ""
    if [ -z "$DB_PASSWORD" ]; then
        log_error "Password cannot be empty"
        exit 1
    fi
fi

# Enable systemd service
echo ""
read -p "Enable systemd service (auto-start on boot)? (Y/n): " ENABLE_SERVICE
ENABLE_SERVICE=${ENABLE_SERVICE:-Y}

# Configure firewall
echo ""
read -p "Configure firewall (ufw)? (Y/n): " CONFIGURE_FIREWALL
CONFIGURE_FIREWALL=${CONFIGURE_FIREWALL:-Y}

echo ""
log_info "Starting installation..."
echo ""

# Update system
log_info "Updating system packages..."
sudo apt update
sudo apt upgrade -y

# Install dependencies
log_info "Installing dependencies..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    wget \
    htop \
    iotop \
    nethogs \
    net-tools \
    ufw

if [ "$BACKEND_CHOICE" == "1" ]; then
    log_info "Installing PostgreSQL..."
    sudo apt install -y postgresql postgresql-contrib
else
    log_info "Using SQLite (file-based) backend"
fi

# Create mlflow system user
log_info "Creating mlflow system user..."
if id "mlflow" &>/dev/null; then
    log_warning "User 'mlflow' already exists, skipping creation"
else
    sudo useradd -r -s /bin/bash -d /opt/mlflow -m mlflow
    log_success "Created mlflow user"
fi

# Create directories
log_info "Creating MLflow directories..."
sudo mkdir -p /opt/mlflow/{mlruns,artifacts,backups}
sudo chown -R mlflow:mlflow /opt/mlflow
log_success "Directories created"

# Setup PostgreSQL (if selected)
if [ "$BACKEND_CHOICE" == "1" ]; then
    log_info "Configuring PostgreSQL..."
    
    # Create database and user
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS mlflow_db;" 2>/dev/null || true
    sudo -u postgres psql -c "DROP USER IF EXISTS mlflow;" 2>/dev/null || true
    sudo -u postgres psql -c "CREATE USER mlflow WITH PASSWORD '$DB_PASSWORD';"
    sudo -u postgres psql -c "CREATE DATABASE mlflow_db OWNER mlflow;"
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE mlflow_db TO mlflow;"
    
    BACKEND_URI="postgresql://mlflow:$DB_PASSWORD@localhost/mlflow_db"
    log_success "PostgreSQL configured"
else
    BACKEND_URI="sqlite:////opt/mlflow/mlflow.db"
    log_success "SQLite backend configured"
fi

# Install MLflow in virtual environment
log_info "Installing MLflow in virtual environment..."
sudo -u mlflow bash << EOF
cd /opt/mlflow
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install mlflow psycopg2-binary gunicorn
deactivate
EOF
log_success "MLflow installed"

# Create systemd service file
log_info "Creating systemd service..."
sudo tee /etc/systemd/system/mlflow.service > /dev/null << EOF
[Unit]
Description=MLflow Tracking Server
Documentation=https://mlflow.org/docs/latest/tracking.html
After=network.target
$([ "$BACKEND_CHOICE" == "1" ] && echo "After=postgresql.service")

[Service]
Type=simple
User=mlflow
Group=mlflow
WorkingDirectory=/opt/mlflow
Environment="PATH=/opt/mlflow/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="MLFLOW_HOME=/opt/mlflow"
ExecStart=/opt/mlflow/venv/bin/mlflow server \\
    --backend-store-uri $BACKEND_URI \\
    --default-artifact-root file:///opt/mlflow/artifacts \\
    --host 0.0.0.0 \\
    --port $MLFLOW_PORT
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
log_success "Systemd service created"

# Reload systemd
sudo systemctl daemon-reload

# Enable and start service (if requested)
if [[ $ENABLE_SERVICE =~ ^[Yy]$ ]]; then
    log_info "Enabling MLflow service..."
    sudo systemctl enable mlflow
    sudo systemctl start mlflow
    sleep 3
    
    if sudo systemctl is-active --quiet mlflow; then
        log_success "MLflow service started successfully"
    else
        log_error "MLflow service failed to start. Check logs: sudo journalctl -u mlflow -n 50"
        exit 1
    fi
else
    log_info "Skipping service enable. Start manually: sudo systemctl start mlflow"
fi

# Configure firewall (if requested)
if [[ $CONFIGURE_FIREWALL =~ ^[Yy]$ ]]; then
    log_info "Configuring firewall..."
    
    # Enable ufw if not already
    sudo ufw --force enable
    
    # Allow SSH (important!)
    sudo ufw allow ssh
    
    # Allow MLflow from local network only (adjust subnet as needed)
    sudo ufw allow from 192.168.0.0/16 to any port $MLFLOW_PORT
    sudo ufw allow from 10.0.0.0/8 to any port $MLFLOW_PORT
    sudo ufw allow from 172.16.0.0/12 to any port $MLFLOW_PORT
    
    log_success "Firewall configured (local network access only)"
fi

# Get local IP address
LOCAL_IP=$(hostname -I | awk '{print $1}')

# Create backup script
log_info "Creating backup script..."
sudo tee /opt/mlflow/backup.sh > /dev/null << 'EOF'
#!/bin/bash
# MLflow Backup Script
# Runs daily via cron at 2 AM

BACKUP_DIR="/opt/mlflow/backups"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup directory if doesn't exist
mkdir -p "$BACKUP_DIR"

# Backup database (if PostgreSQL)
if systemctl is-active --quiet postgresql; then
    echo "Backing up PostgreSQL database..."
    sudo -u postgres pg_dump mlflow_db > "$BACKUP_DIR/mlflow_db_$DATE.sql"
    gzip "$BACKUP_DIR/mlflow_db_$DATE.sql"
fi

# Backup mlruns directory
echo "Backing up mlruns..."
tar -czf "$BACKUP_DIR/mlruns_$DATE.tar.gz" -C /opt/mlflow mlruns

# Backup artifacts
echo "Backing up artifacts..."
tar -czf "$BACKUP_DIR/artifacts_$DATE.tar.gz" -C /opt/mlflow artifacts

# Keep only last 7 days of backups
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +7 -delete
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +7 -delete

echo "Backup completed: $DATE"
EOF

sudo chmod +x /opt/mlflow/backup.sh
sudo chown mlflow:mlflow /opt/mlflow/backup.sh

# Add to crontab (daily at 2 AM)
(sudo crontab -l 2>/dev/null | grep -v '/opt/mlflow/backup.sh'; echo "0 2 * * * /opt/mlflow/backup.sh >> /var/log/mlflow_backup.log 2>&1") | sudo crontab -

log_success "Backup script created (runs daily at 2 AM)"

# Installation summary
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "              Installation Complete!"
echo "════════════════════════════════════════════════════════════════"
echo ""
log_success "MLflow Tracking Server is running!"
echo ""
echo "Access URLs:"
echo "  Local:          http://localhost:$MLFLOW_PORT"
echo "  LAN:            http://$LOCAL_IP:$MLFLOW_PORT"
echo ""
echo "Configuration:"
echo "  Backend:        $([ "$BACKEND_CHOICE" == "1" ] && echo "PostgreSQL" || echo "SQLite")"
echo "  Storage:        /opt/mlflow/mlruns/"
echo "  Artifacts:      /opt/mlflow/artifacts/"
echo "  Backups:        /opt/mlflow/backups/"
echo "  Service:        $([ "$ENABLE_SERVICE" == "Y" ] && echo "Enabled (auto-start)" || echo "Disabled")"
echo ""
echo "Useful Commands:"
echo "  Check status:   sudo systemctl status mlflow"
echo "  View logs:      sudo journalctl -u mlflow -f"
echo "  Restart:        sudo systemctl restart mlflow"
echo "  Stop:           sudo systemctl stop mlflow"
echo "  Manual backup:  sudo /opt/mlflow/backup.sh"
echo ""
echo "Next Steps:"
echo "  1. Test local access: curl http://localhost:$MLFLOW_PORT"
echo "  2. Setup remote access: bash setup_tailscale_vpn.sh"
echo "  3. Configure dev machine: export MLFLOW_TRACKING_URI=\"http://$LOCAL_IP:$MLFLOW_PORT\""
echo ""
echo "Documentation: See README.md in this directory"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Test connection
log_info "Testing MLflow connection..."
sleep 2
if curl -s http://localhost:$MLFLOW_PORT >/dev/null; then
    log_success "✓ MLflow UI is accessible!"
else
    log_warning "Could not connect to MLflow UI. Check service status: sudo systemctl status mlflow"
fi

echo ""
log_info "Setup complete! 🎉"
