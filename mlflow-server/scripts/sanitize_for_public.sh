#!/bin/bash
# Sanitize repository for public sharing
# This script replaces sensitive information with placeholders

set -e

echo "======================================================================"
echo "Repository Sanitization Script"
echo "======================================================================"
echo ""
echo "This script will replace sensitive information with placeholders:"
echo "  - IP addresses (<SERVER_IP> → <SERVER_IP>)"
echo "  - IP addresses (<TRAINING_IP> → <TRAINING_IP>)"
echo "  - Passwords (mlflowpass123 → <YOUR_PASSWORD>)"
echo "  - Connection strings with embedded credentials"
echo ""
echo "WARNING: This modifies files in place!"
echo "         Make sure you have committed or backed up your work first."
echo ""
read -p "Continue? (y/N): " confirm

if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Starting sanitization..."
echo ""

# Counter for changes
TOTAL_CHANGES=0

# Replace server IP
echo "[1/5] Replacing server IP addresses..."
COUNT=$(find . -name "*.md" -type f -exec sed -i 's/100\.69\.227\.36/<SERVER_IP>/g' {} + -exec echo {} \; | wc -l)
TOTAL_CHANGES=$((TOTAL_CHANGES + COUNT))
echo "      ✓ Updated $COUNT files"

# Replace training machine IP
echo "[2/5] Replacing training machine IP addresses..."
COUNT=$(find . -name "*.md" -type f -exec sed -i 's/100\.74\.54\.36/<TRAINING_IP>/g' {} + -exec echo {} \; | wc -l)
TOTAL_CHANGES=$((TOTAL_CHANGES + COUNT))
echo "      ✓ Updated $COUNT files"

# Replace default password
echo "[3/5] Replacing password references..."
COUNT=$(find . -name "*.md" -type f -exec sed -i 's/mlflowpass123/<YOUR_PASSWORD>/g' {} + -exec echo {} \; | wc -l)
TOTAL_CHANGES=$((TOTAL_CHANGES + COUNT))
echo "      ✓ Updated $COUNT files"

# Replace connection strings
echo "[4/5] Replacing PostgreSQL connection strings..."
COUNT=$(find . -name "*.md" -type f -exec sed -i 's|postgresql://mlflow:[^@]*@localhost|postgresql://mlflow:<YOUR_PASSWORD>@localhost|g' {} + -exec echo {} \; | wc -l)
TOTAL_CHANGES=$((TOTAL_CHANGES + COUNT))
echo "      ✓ Updated $COUNT files"

# Replace any remaining password patterns
echo "[5/5] Replacing PGPASSWORD references..."
COUNT=$(find . -name "*.md" -type f -exec sed -i "s/PGPASSWORD='[^']*'/PGPASSWORD='<YOUR_PASSWORD>'/g" {} + -exec echo {} \; | wc -l)
COUNT=$((COUNT + $(find . -name "*.md" -type f -exec sed -i 's/PGPASSWORD="[^"]*"/PGPASSWORD="<YOUR_PASSWORD>"/g' {} + -exec echo {} \; | wc -l)))
TOTAL_CHANGES=$((TOTAL_CHANGES + COUNT))
echo "      ✓ Updated $COUNT files"

echo ""
echo "======================================================================"
echo "Sanitization Complete!"
echo "======================================================================"
echo ""
echo "Total changes: $TOTAL_CHANGES"
echo ""
echo "Next steps:"
echo "  1. Review changes: git diff"
echo "  2. Test documentation for broken references"
echo "  3. Commit changes: git add . && git commit -m 'Sanitize for public sharing'"
echo "  4. Push to repository"
echo ""
echo "To restore original values, use git checkout on modified files"
echo "or restore from your backup."
echo ""
