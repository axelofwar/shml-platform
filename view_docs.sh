#!/bin/bash
# Quick access to all documentation

echo "=============================================="
echo "ML Platform Documentation Access"
echo "=============================================="
echo ""
echo "Public Documentation (safe to commit):"
echo "  1. ARCHITECTURE.md              - Tool decisions and integration"
echo "  2. REMOTE_ACCESS_GUIDE.md       - Remote client setup"
echo "  3. ml-platform/mlflow-server/README.md      - MLflow stack overview"
echo "  4. ml-platform/mlflow-server/QUICK_REFERENCE.md - Quick commands"
echo "  5. ml-platform/ray_compute/README.md        - Ray Compute overview"
echo ""
echo "Private Documentation (git-ignored):"
echo "  6. ACCESS_GUIDE.md              - ALL credentials and URLs"
echo "  7. DEPLOYMENT_SUMMARY.md        - Full deployment details"
echo "  8. CURRENT_DEPLOYMENT.md        - MLflow deployment status"
echo "  9. .env.credentials files       - All credentials"
echo " 10. GIT_SAFETY_CHECK.md          - Git safety guidelines"
echo ""
echo "=============================================="
echo ""

# Parse command line argument
case "$1" in
    1) less ARCHITECTURE.md ;;
    2) less REMOTE_ACCESS_GUIDE.md ;;
    3) less ml-platform/mlflow-server/README.md ;;
    4) less ml-platform/mlflow-server/QUICK_REFERENCE.md ;;
    5) less ml-platform/ray_compute/README.md ;;
    6) less ACCESS_GUIDE.md ;;
    7) less DEPLOYMENT_SUMMARY.md ;;
    8) less ml-platform/mlflow-server/CURRENT_DEPLOYMENT.md ;;
    9) 
        echo "Credentials files:"
        echo "  - ml-platform/mlflow-server/.env.credentials"
        echo "  - ml-platform/ray_compute/.env.credentials"
        echo ""
        read -p "View which file? [1=mlflow, 2=ray]: " choice
        case "$choice" in
            1) less ml-platform/mlflow-server/.env.credentials ;;
            2) less ml-platform/ray_compute/.env.credentials ;;
            *) echo "Invalid choice" ;;
        esac
        ;;
    10) less GIT_SAFETY_CHECK.md ;;
    *)
        read -p "Enter number (1-10) or 'q' to quit: " choice
        if [ "$choice" != "q" ]; then
            $0 $choice
        fi
        ;;
esac
