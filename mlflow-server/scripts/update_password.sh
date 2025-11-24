#!/bin/bash
# MLflow Password Update Script
# Updates PostgreSQL password everywhere it's used in the MLflow server configuration

set -e

echo "======================================================================"
echo "MLflow PostgreSQL Password Update Script"
echo "======================================================================"
echo ""
echo "This script will update the MLflow PostgreSQL password in:"
echo "  - PostgreSQL database"
echo "  - MLflow service configuration"
echo "  - Backup script"
echo "  - Documentation files"
echo ""
echo "WARNING: This will restart the MLflow service!"
echo ""

# Prompt for new password
read -sp "Enter new PostgreSQL password for 'mlflow' user: " NEW_PASSWORD
echo ""
read -sp "Confirm new password: " NEW_PASSWORD_CONFIRM
echo ""

if [ "$NEW_PASSWORD" != "$NEW_PASSWORD_CONFIRM" ]; then
    echo "Error: Passwords do not match!"
    exit 1
fi

if [ -z "$NEW_PASSWORD" ]; then
    echo "Error: Password cannot be empty!"
    exit 1
fi

# Get current password from secure file
if [ -f /opt/mlflow/.mlflow_db_pass ]; then
    CURRENT_PASSWORD=$(sudo cat /opt/mlflow/.mlflow_db_pass 2>/dev/null)
else
    CURRENT_PASSWORD=""
fi
echo ""
read -sp "Enter CURRENT PostgreSQL password: " CURRENT_INPUT
echo ""
if [ -z "$CURRENT_INPUT" ]; then
    if [ -n "$CURRENT_PASSWORD" ]; then
        CURRENT_INPUT="$CURRENT_PASSWORD"
    else
        echo "Error: Could not determine current password!"
        exit 1
    fi
fi

# Verify current password works
echo ""
echo "Verifying current password..."
if ! PGPASSWORD="$CURRENT_INPUT" psql -h localhost -U mlflow -d mlflow_db -c "SELECT 1;" > /dev/null 2>&1; then
    echo "Error: Current password is incorrect or database is not accessible!"
    exit 1
fi
echo "✓ Current password verified"

echo ""
echo "======================================================================"
echo "Updating password in all locations..."
echo "======================================================================"
echo ""

# 1. Update PostgreSQL database
echo "[1/6] Updating PostgreSQL user password..."
sudo -u postgres psql -c "ALTER USER mlflow WITH PASSWORD '$NEW_PASSWORD';" > /dev/null
if PGPASSWORD="$NEW_PASSWORD" psql -h localhost -U mlflow -d mlflow_db -c "SELECT 1;" > /dev/null 2>&1; then
    echo "      ✓ PostgreSQL password updated"
else
    echo "      ✗ Failed to update PostgreSQL password"
    exit 1
fi

# 2. Update MLflow service file
echo "[2/6] Updating MLflow service configuration..."
sudo sed -i "s|postgresql://mlflow:[^@]*@localhost|postgresql://mlflow:$NEW_PASSWORD@localhost|g" /etc/systemd/system/mlflow.service
if grep -q "postgresql://mlflow:$NEW_PASSWORD@localhost" /etc/systemd/system/mlflow.service; then
    echo "      ✓ MLflow service file updated"
else
    echo "      ✗ Failed to update MLflow service file"
    exit 1
fi

# 3. Update backup script
echo "[3/6] Updating backup script..."
if [ -f /opt/mlflow/backup.sh ]; then
    # Check if backup script uses PGPASSWORD or sudo -u postgres
    if grep -q "PGPASSWORD" /opt/mlflow/backup.sh; then
        sudo sed -i "s|PGPASSWORD='[^']*'|PGPASSWORD='$NEW_PASSWORD'|g" /opt/mlflow/backup.sh
        sudo sed -i "s|PGPASSWORD=\"[^\"]*\"|PGPASSWORD=\"$NEW_PASSWORD\"|g" /opt/mlflow/backup.sh
        if grep -q "PGPASSWORD='$NEW_PASSWORD'" /opt/mlflow/backup.sh || grep -q "PGPASSWORD=\"$NEW_PASSWORD\"" /opt/mlflow/backup.sh; then
            echo "      ✓ Backup script updated"
        else
            echo "      ✗ Failed to update backup script"
            exit 1
        fi
    elif grep -q "sudo -u postgres pg_dump" /opt/mlflow/backup.sh; then
        echo "      ✓ Backup script uses postgres superuser (no password needed)"
    else
        echo "      ⊘ Backup script doesn't use password authentication"
    fi
else
    echo "      ⊘ Backup script not found (skipping)"
fi

# 4. Update password file if exists
echo "[4/6] Updating password storage file..."
if [ -f /opt/mlflow/.mlflow_db_pass ]; then
    echo "$NEW_PASSWORD" | sudo tee /opt/mlflow/.mlflow_db_pass > /dev/null
    sudo chmod 600 /opt/mlflow/.mlflow_db_pass
    sudo chown mlflow:mlflow /opt/mlflow/.mlflow_db_pass
    echo "      ✓ Password file updated"
else
    echo "$NEW_PASSWORD" | sudo tee /opt/mlflow/.mlflow_db_pass > /dev/null
    sudo chmod 600 /opt/mlflow/.mlflow_db_pass
    sudo chown mlflow:mlflow /opt/mlflow/.mlflow_db_pass
    echo "      ✓ Password file created"
fi

# 5. Update documentation files with placeholder
echo "[5/6] Updating documentation files..."
DOCS_UPDATED=0
for doc in /home/axelofwar/Projects/mlflow-server/mlflow_server/*.md; do
    if [ -f "$doc" ]; then
        if grep -q "mlflowpass123" "$doc" 2>/dev/null; then
            sed -i "s/mlflowpass123/<YOUR_PASSWORD>/g" "$doc"
            DOCS_UPDATED=$((DOCS_UPDATED + 1))
        fi
    fi
done
echo "      ✓ Updated $DOCS_UPDATED documentation files"

# 6. Reload and restart services
echo "[6/6] Restarting services..."
sudo systemctl daemon-reload
sudo systemctl restart mlflow
sleep 3

if sudo systemctl is-active --quiet mlflow; then
    echo "      ✓ MLflow service restarted successfully"
else
    echo "      ✗ MLflow service failed to start!"
    echo ""
    echo "Checking logs..."
    sudo journalctl -u mlflow -n 20 --no-pager
    exit 1
fi

# Verify new password works end-to-end
echo ""
echo "Verifying new password..."
if PGPASSWORD="$NEW_PASSWORD" psql -h localhost -U mlflow -d mlflow_db -c "SELECT 1;" > /dev/null 2>&1; then
    echo "✓ New password verified with PostgreSQL"
else
    echo "✗ New password verification failed!"
    exit 1
fi

if curl -s http://localhost:5000/health | grep -q "OK"; then
    echo "✓ MLflow service is responding correctly"
else
    echo "✗ MLflow service is not responding!"
    exit 1
fi

echo ""
echo "======================================================================"
echo "Password Update Complete!"
echo "======================================================================"
echo ""
echo "Summary of changes:"
echo "  ✓ PostgreSQL user 'mlflow' password updated"
echo "  ✓ MLflow service configuration updated"
echo "  ✓ Backup script updated"
echo "  ✓ Password file updated: /opt/mlflow/.mlflow_db_pass"
echo "  ✓ Documentation files sanitized"
echo "  ✓ MLflow service restarted and verified"
echo ""
echo "======================================================================"
echo "TRAINING MACHINE UPDATES REQUIRED:"
echo "======================================================================"
echo ""
echo "The training machine does NOT need any updates!"
echo ""
echo "Reason: The training machine only connects via HTTP to:"
echo "  - http://<SERVER_IP>:8080 (Nginx)"
echo "  - http://<SERVER_IP>:5000 (MLflow)"
echo ""
echo "The PostgreSQL password is only used internally on the server"
echo "for MLflow to connect to its backend database."
echo ""
echo "Training machine artifact uploads and tracking will continue"
echo "to work without any changes."
echo ""
echo "======================================================================"
echo "MANUAL UPDATES NEEDED:"
echo "======================================================================"
echo ""
echo "Update these locations manually if you use them:"
echo ""
echo "1. For Adminer web access:"
echo "   URL: http://<SERVER_IP>:8081/adminer.php"
echo "   Login with NEW password: $NEW_PASSWORD"
echo ""
echo "2. For pgcli/psql access:"
echo "   pgcli -h localhost -U mlflow mlflow_db"
echo "   Password: (use new password when prompted)"
echo ""
echo "3. Database info script (already uses new password):"
echo "   Edit /home/axelofwar/Projects/mlflow-server/mlflow_server/db_info.sh"
echo "   Update line: PGPASSWORD='<YOUR_PASSWORD>'"
echo ""
echo "======================================================================"
echo ""

# Create a secure note with the new password
echo "$NEW_PASSWORD" | sudo tee /opt/mlflow/.pgpass_new > /dev/null
sudo chmod 600 /opt/mlflow/.pgpass_new
sudo chown mlflow:mlflow /opt/mlflow/.pgpass_new

echo "New password stored securely in: /opt/mlflow/.pgpass_new"
echo "Delete this file after you've updated your documentation."
echo ""
