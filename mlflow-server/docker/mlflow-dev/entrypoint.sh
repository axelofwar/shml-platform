#!/bin/bash
# MLflow 3.x Dev Server Entrypoint
set -e

echo "=============================================="
echo "  MLflow 3.x Development Server"
echo "=============================================="
echo ""

# Print version info
echo "📦 Package Versions:"
python -c "import mlflow; print(f'   MLflow: {mlflow.__version__}')"
python -c "import sqlalchemy; print(f'   SQLAlchemy: {sqlalchemy.__version__}')"
python -c "import pydantic; print(f'   Pydantic: {pydantic.__version__}')"
echo ""

# Environment configuration
MLFLOW_HOST="${MLFLOW_HOST:-0.0.0.0}"
MLFLOW_PORT="${MLFLOW_PORT:-5001}"
MLFLOW_WORKERS="${MLFLOW_WORKERS:-4}"
MLFLOW_BACKEND_STORE_URI="${MLFLOW_BACKEND_STORE_URI:-sqlite:///mlflow/mlruns/mlflow.db}"
MLFLOW_ARTIFACT_ROOT="${MLFLOW_ARTIFACT_ROOT:-/mlflow/artifacts}"

echo "🔧 Configuration:"
echo "   Host: $MLFLOW_HOST"
echo "   Port: $MLFLOW_PORT"
echo "   Workers: $MLFLOW_WORKERS"
echo "   Backend: $MLFLOW_BACKEND_STORE_URI"
echo "   Artifacts: $MLFLOW_ARTIFACT_ROOT"
echo ""

# Wait for database if using PostgreSQL
if [[ "$MLFLOW_BACKEND_STORE_URI" == postgresql* ]]; then
    echo "⏳ Waiting for PostgreSQL..."

    # Extract host from URI
    DB_HOST=$(echo "$MLFLOW_BACKEND_STORE_URI" | sed -n 's/.*@\([^:\/]*\).*/\1/p')
    DB_PORT=$(echo "$MLFLOW_BACKEND_STORE_URI" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
    DB_PORT="${DB_PORT:-5432}"

    for i in {1..30}; do
        if pg_isready -h "$DB_HOST" -p "$DB_PORT" > /dev/null 2>&1; then
            echo "   ✅ PostgreSQL is ready"
            break
        fi
        echo "   Waiting for PostgreSQL... ($i/30)"
        sleep 2
    done
fi

# Run database migrations/upgrades
echo ""
echo "🔄 Running MLflow database upgrade..."
mlflow db upgrade "$MLFLOW_BACKEND_STORE_URI" 2>&1 || echo "   ⚠️  DB upgrade skipped or already current"

echo ""
echo "🚀 Starting MLflow Dev Server..."
echo "=============================================="

# Start MLflow server with gunicorn
exec mlflow server \
    --host "$MLFLOW_HOST" \
    --port "$MLFLOW_PORT" \
    --backend-store-uri "$MLFLOW_BACKEND_STORE_URI" \
    --default-artifact-root "$MLFLOW_ARTIFACT_ROOT" \
    --workers "$MLFLOW_WORKERS" \
    --gunicorn-opts "--timeout 120 --keep-alive 5"
