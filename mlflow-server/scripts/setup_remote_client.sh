#!/bin/bash
################################################################################
# MLflow Remote Client Setup Script
# Purpose: Configure remote machine to connect to MLflow server
# Works on: Same network OR different networks (via Tailscale VPN)
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
MLFLOW_SERVER_HOST="${MLFLOW_SERVER_HOST:-}"  # Set via environment or prompt
MLFLOW_TRACKING_PORT="${MLFLOW_TRACKING_PORT:-8080}"
USE_TAILSCALE="${USE_TAILSCALE:-auto}"  # auto, yes, no

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   MLflow Remote Client Setup${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

################################################################################
# Step 1: Detect or prompt for server host
################################################################################
if [ -z "$MLFLOW_SERVER_HOST" ]; then
    echo -e "${YELLOW}Enter the MLflow server host (IP address or hostname):${NC}"
    echo -e "  ${BLUE}Tip:${NC} If on same network, use server's local IP (e.g., 192.168.1.100)"
    echo -e "  ${BLUE}Tip:${NC} If using Tailscale, use Tailscale IP (e.g., 100.x.x.x)"
    read -p "Server host: " MLFLOW_SERVER_HOST

    if [ -z "$MLFLOW_SERVER_HOST" ]; then
        echo -e "${RED}Error: Server host is required${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✓${NC} Using MLflow server: ${BLUE}$MLFLOW_SERVER_HOST:$MLFLOW_TRACKING_PORT${NC}"
echo ""

################################################################################
# Step 2: Test connectivity
################################################################################
echo -e "${YELLOW}Testing connectivity to MLflow server...${NC}"

if command -v curl &> /dev/null; then
    if curl -f -s --connect-timeout 5 "http://$MLFLOW_SERVER_HOST:$MLFLOW_TRACKING_PORT/health" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Successfully connected to MLflow server!"
        CONNECTIVITY="ok"
    else
        echo -e "${RED}✗${NC} Cannot reach MLflow server at http://$MLFLOW_SERVER_HOST:$MLFLOW_TRACKING_PORT"
        CONNECTIVITY="failed"
    fi
else
    echo -e "${YELLOW}⚠${NC}  curl not found, skipping connectivity test"
    CONNECTIVITY="unknown"
fi
echo ""

################################################################################
# Step 3: Offer Tailscale setup if connectivity failed
################################################################################
if [ "$CONNECTIVITY" = "failed" ] && [ "$USE_TAILSCALE" != "no" ]; then
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  Connection failed. Would you like to set up Tailscale VPN?${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "Tailscale creates a secure VPN between your machines, allowing"
    echo -e "access even across different networks or the internet."
    echo ""

    if [ "$USE_TAILSCALE" = "auto" ]; then
        read -p "Set up Tailscale VPN? (y/n): " setup_tailscale
    else
        setup_tailscale="y"
    fi

    if [ "$setup_tailscale" = "y" ] || [ "$setup_tailscale" = "Y" ]; then
        echo ""
        echo -e "${BLUE}Installing Tailscale...${NC}"

        # Detect OS and install Tailscale
        if [ -f /etc/os-release ]; then
            . /etc/os-release
            OS=$ID
        else
            OS=$(uname -s)
        fi

        case "$OS" in
            ubuntu|debian)
                echo -e "${BLUE}→${NC} Installing for Debian/Ubuntu..."
                curl -fsSL https://tailscale.com/install.sh | sh
                ;;
            fedora|rhel|centos)
                echo -e "${BLUE}→${NC} Installing for RHEL/Fedora/CentOS..."
                curl -fsSL https://tailscale.com/install.sh | sh
                ;;
            arch)
                echo -e "${BLUE}→${NC} Installing for Arch Linux..."
                sudo pacman -S tailscale
                ;;
            Darwin)
                echo -e "${BLUE}→${NC} Installing for macOS..."
                if command -v brew &> /dev/null; then
                    brew install tailscale
                else
                    echo -e "${YELLOW}Please install Tailscale from: https://tailscale.com/download${NC}"
                    exit 1
                fi
                ;;
            *)
                echo -e "${YELLOW}Unsupported OS. Please install Tailscale manually from: https://tailscale.com/download${NC}"
                exit 1
                ;;
        esac

        echo ""
        echo -e "${BLUE}Starting Tailscale...${NC}"
        sudo tailscale up

        echo ""
        echo -e "${GREEN}✓${NC} Tailscale installed and connected!"
        echo ""
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${YELLOW}  IMPORTANT: Update MLFLOW_SERVER_HOST${NC}"
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo ""
        echo -e "1. On the MLflow server machine, run: ${BLUE}tailscale ip -4${NC}"
        echo -e "2. Note the Tailscale IP (starts with 100.x.x.x)"
        echo -e "3. Re-run this script with that IP:"
        echo ""
        echo -e "   ${GREEN}MLFLOW_SERVER_HOST=<tailscale-ip> ./setup_remote_client.sh${NC}"
        echo ""
        exit 0
    fi
fi

################################################################################
# Step 4: Install Python and dependencies
################################################################################
echo -e "${YELLOW}Checking Python installation...${NC}"

if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | awk '{print $2}')
    echo -e "${GREEN}✓${NC} Python $PYTHON_VERSION found"
else
    echo -e "${RED}✗${NC} Python 3 not found"
    echo -e "${BLUE}Installing Python 3...${NC}"

    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
    fi

    case "$OS" in
        ubuntu|debian)
            sudo apt-get update
            sudo apt-get install -y python3 python3-pip python3-venv
            ;;
        fedora|rhel|centos)
            sudo yum install -y python3 python3-pip
            ;;
        arch)
            sudo pacman -S python python-pip
            ;;
        *)
            echo -e "${RED}Please install Python 3 manually${NC}"
            exit 1
            ;;
    esac
fi
echo ""

################################################################################
# Step 5: Create virtual environment and install MLflow
################################################################################
echo -e "${YELLOW}Setting up MLflow client environment...${NC}"

VENV_DIR="$HOME/.mlflow-client"

if [ -d "$VENV_DIR" ]; then
    echo -e "${BLUE}→${NC} Virtual environment already exists at $VENV_DIR"
    read -p "Recreate it? (y/n): " recreate
    if [ "$recreate" = "y" ]; then
        rm -rf "$VENV_DIR"
    fi
fi

if [ ! -d "$VENV_DIR" ]; then
    echo -e "${BLUE}→${NC} Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo -e "${BLUE}→${NC} Activating virtual environment..."
source "$VENV_DIR/bin/activate"

echo -e "${BLUE}→${NC} Installing MLflow and dependencies..."
pip install --upgrade pip > /dev/null
pip install mlflow==2.17.2 > /dev/null
pip install requests urllib3 > /dev/null

echo -e "${GREEN}✓${NC} MLflow client installed"
echo ""

################################################################################
# Step 6: Configure environment
################################################################################
echo -e "${YELLOW}Configuring MLflow environment...${NC}"

# Create config directory
CONFIG_DIR="$HOME/.mlflow"
mkdir -p "$CONFIG_DIR"

# Create environment file
ENV_FILE="$CONFIG_DIR/remote.env"
cat > "$ENV_FILE" << EOF
# MLflow Remote Server Configuration
# Generated: $(date)

export MLFLOW_TRACKING_URI="http://$MLFLOW_SERVER_HOST:$MLFLOW_TRACKING_PORT"
export MLFLOW_EXPERIMENT_NAME="default"

# Optional: Set default artifact root (if using shared storage)
# export MLFLOW_ARTIFACT_LOCATION="s3://bucket/path" or "file:///shared/path"

# Virtual environment
export MLFLOW_VENV="$VENV_DIR"

# Helper function to activate MLflow environment
mlflow_env() {
    source "\$MLFLOW_VENV/bin/activate"
    echo "MLflow environment activated"
    echo "Tracking URI: \$MLFLOW_TRACKING_URI"
}
EOF

echo -e "${GREEN}✓${NC} Configuration saved to: ${BLUE}$ENV_FILE${NC}"
echo ""

################################################################################
# Step 7: Create test script
################################################################################
echo -e "${YELLOW}Creating test script...${NC}"

TEST_SCRIPT="$CONFIG_DIR/test_connection.py"
cat > "$TEST_SCRIPT" << 'EOFPYTHON'
#!/usr/bin/env python3
"""Test MLflow connection to remote server"""
import os
import sys
import mlflow
from mlflow.tracking import MlflowClient

def test_connection():
    tracking_uri = os.environ.get('MLFLOW_TRACKING_URI')

    if not tracking_uri:
        print("❌ MLFLOW_TRACKING_URI not set")
        print("Run: source ~/.mlflow/remote.env")
        return False

    print(f"🔗 Connecting to: {tracking_uri}")

    try:
        # Set tracking URI
        mlflow.set_tracking_uri(tracking_uri)
        client = MlflowClient()

        # Test connection by listing experiments
        experiments = client.search_experiments()

        print(f"✅ Successfully connected!")
        print(f"📊 Found {len(experiments)} experiment(s):")
        for exp in experiments[:5]:  # Show first 5
            print(f"   • {exp.name} (ID: {exp.experiment_id})")

        return True

    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print("\nTroubleshooting:")
        print("1. Check server is running: docker compose ps")
        print("2. Check firewall allows port 8080")
        print("3. Test connectivity: curl http://<server>:8080/health")
        return False

if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)
EOFPYTHON

chmod +x "$TEST_SCRIPT"
echo -e "${GREEN}✓${NC} Test script created: ${BLUE}$TEST_SCRIPT${NC}"
echo ""

################################################################################
# Step 8: Create example training script
################################################################################
echo -e "${YELLOW}Creating example training script...${NC}"

EXAMPLE_SCRIPT="$CONFIG_DIR/example_training.py"
cat > "$EXAMPLE_SCRIPT" << 'EOFPYTHON'
#!/usr/bin/env python3
"""Example MLflow training script for remote server"""
import mlflow
import mlflow.sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import os

def train_model():
    # Ensure tracking URI is set
    tracking_uri = os.environ.get('MLFLOW_TRACKING_URI')
    if not tracking_uri:
        print("❌ MLFLOW_TRACKING_URI not set")
        print("Run: source ~/.mlflow/remote.env")
        return

    print(f"🔗 Using MLflow server: {tracking_uri}")
    mlflow.set_tracking_uri(tracking_uri)

    # Set experiment
    mlflow.set_experiment("remote-training-example")

    # Load data
    print("📊 Loading dataset...")
    iris = load_iris()
    X_train, X_test, y_train, y_test = train_test_split(
        iris.data, iris.target, test_size=0.2, random_state=42
    )

    # Start MLflow run
    with mlflow.start_run(run_name="random-forest-iris"):
        print("🚀 Training model...")

        # Train model
        n_estimators = 100
        max_depth = 5

        clf = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            random_state=42
        )
        clf.fit(X_train, y_train)

        # Predict and evaluate
        y_pred = clf.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)

        # Log parameters
        mlflow.log_param("n_estimators", n_estimators)
        mlflow.log_param("max_depth", max_depth)

        # Log metrics
        mlflow.log_metric("accuracy", accuracy)

        # Log model
        mlflow.sklearn.log_model(clf, "model")

        print(f"✅ Training complete!")
        print(f"   Accuracy: {accuracy:.4f}")
        print(f"   Run ID: {mlflow.active_run().info.run_id}")
        print(f"\n🌐 View in MLflow UI: {tracking_uri}")

if __name__ == "__main__":
    train_model()
EOFPYTHON

chmod +x "$EXAMPLE_SCRIPT"
echo -e "${GREEN}✓${NC} Example script created: ${BLUE}$EXAMPLE_SCRIPT${NC}"
echo ""

################################################################################
# Step 9: Add to shell profile for persistence
################################################################################
echo -e "${YELLOW}Adding configuration to shell profile...${NC}"

SHELL_PROFILE=""
if [ -n "$BASH_VERSION" ]; then
    SHELL_PROFILE="$HOME/.bashrc"
elif [ -n "$ZSH_VERSION" ]; then
    SHELL_PROFILE="$HOME/.zshrc"
fi

if [ -n "$SHELL_PROFILE" ]; then
    if ! grep -q "mlflow/remote.env" "$SHELL_PROFILE" 2>/dev/null; then
        cat >> "$SHELL_PROFILE" << 'EOF'

# MLflow Remote Client Configuration
if [ -f "$HOME/.mlflow/remote.env" ]; then
    source "$HOME/.mlflow/remote.env"
fi
EOF
        echo -e "${GREEN}✓${NC} Added to $SHELL_PROFILE"
    else
        echo -e "${BLUE}→${NC} Already configured in $SHELL_PROFILE"
    fi
fi
echo ""

################################################################################
# Step 10: Final connectivity test
################################################################################
echo -e "${YELLOW}Running final connectivity test...${NC}"
source "$ENV_FILE"
python3 "$TEST_SCRIPT"
TEST_RESULT=$?
echo ""

################################################################################
# Final instructions
################################################################################
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

if [ $TEST_RESULT -eq 0 ]; then
    echo -e "${GREEN}✅ Successfully connected to MLflow server!${NC}"
else
    echo -e "${YELLOW}⚠️  Setup complete but connection test failed${NC}"
    echo -e "   Please check the troubleshooting steps above"
fi

echo ""
echo -e "${YELLOW}Quick Start:${NC}"
echo ""
echo -e "1. ${BLUE}Activate MLflow environment:${NC}"
echo -e "   ${GREEN}source ~/.mlflow/remote.env${NC}"
echo -e "   or"
echo -e "   ${GREEN}mlflow_env${NC}"
echo ""
echo -e "2. ${BLUE}Test connection:${NC}"
echo -e "   ${GREEN}python3 ~/.mlflow/test_connection.py${NC}"
echo ""
echo -e "3. ${BLUE}Run example training:${NC}"
echo -e "   ${GREEN}python3 ~/.mlflow/example_training.py${NC}"
echo ""
echo -e "4. ${BLUE}Use in your own scripts:${NC}"
echo ""
cat << 'EOFCODE'
   import mlflow

   # Tracking URI is already set via environment
   mlflow.set_experiment("my-experiment")

   with mlflow.start_run():
       mlflow.log_param("param1", 5)
       mlflow.log_metric("metric1", 0.85)
EOFCODE
echo ""
echo -e "${YELLOW}Configuration Files:${NC}"
echo -e "  • Environment: ${BLUE}~/.mlflow/remote.env${NC}"
echo -e "  • Test script: ${BLUE}~/.mlflow/test_connection.py${NC}"
echo -e "  • Example: ${BLUE}~/.mlflow/example_training.py${NC}"
echo ""
echo -e "${YELLOW}MLflow Server:${NC}"
echo -e "  • Tracking URI: ${BLUE}http://$MLFLOW_SERVER_HOST:$MLFLOW_TRACKING_PORT${NC}"
echo -e "  • Web UI: ${BLUE}http://$MLFLOW_SERVER_HOST:$MLFLOW_TRACKING_PORT${NC}"
echo ""

if [ "$CONNECTIVITY" = "failed" ]; then
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  Troubleshooting Connection Issues:${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "1. ${BLUE}Check server is running:${NC}"
    echo -e "   ssh <server> 'cd mlflow-server && docker compose ps'"
    echo ""
    echo -e "2. ${BLUE}Check firewall on server:${NC}"
    echo -e "   ssh <server> 'sudo ufw allow 8080/tcp'"
    echo ""
    echo -e "3. ${BLUE}Test from this machine:${NC}"
    echo -e "   curl http://$MLFLOW_SERVER_HOST:$MLFLOW_TRACKING_PORT/health"
    echo ""
    echo -e "4. ${BLUE}Consider Tailscale VPN:${NC}"
    echo -e "   Re-run with: ${GREEN}USE_TAILSCALE=yes ./setup_remote_client.sh${NC}"
    echo ""
fi

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
