#!/bin/bash
set -e

echo "🎯 Creating MLflow Custom Experiments"
echo "======================================"
echo ""

# Use newgrp to get docker permissions, then run Python script inside the MLflow container
newgrp docker << 'EOF'
docker exec mlflow-server python3 << 'EOFPYTHON'
import mlflow
from mlflow.tracking import MlflowClient
import sys

# Connect directly to the MLflow server
mlflow.set_tracking_uri("http://localhost:5000")
client = MlflowClient()

# Define custom experiments
experiments = {
    'production-models': {
        'description': 'Production-ready models deployed to live systems',
        'tags': {
            'environment': 'production',
            'created_by': 'system',
            'purpose': 'deployment',
            'requires_approval': 'true'
        }
    },
    'staging-models': {
        'description': 'Models under evaluation before production deployment',
        'tags': {
            'environment': 'staging',
            'created_by': 'system',
            'purpose': 'evaluation',
            'requires_testing': 'true'
        }
    },
    'development-models': {
        'description': 'Experimental models and development work',
        'tags': {
            'environment': 'development',
            'created_by': 'system',
            'purpose': 'experimentation',
            'requires_validation': 'true'
        }
    },
    'dataset-registry': {
        'description': 'Dataset versioning and lineage tracking',
        'tags': {
            'environment': 'production',
            'created_by': 'system',
            'purpose': 'data-versioning',
            'type': 'dataset-tracking',
            'requires_schema': 'true'
        }
    },
    'model-registry-experiments': {
        'description': 'Experiments for models registered in the model registry',
        'tags': {
            'environment': 'production',
            'created_by': 'system',
            'purpose': 'model-registry',
            'type': 'registry-tracking'
        }
    }
}

print("Creating custom experiments...")
print("=" * 60)

created_count = 0
existing_count = 0

for name, config in experiments.items():
    try:
        # Check if experiment exists
        experiment = client.get_experiment_by_name(name)
        
        if experiment:
            print(f"✓ '{name}' already exists (ID: {experiment.experiment_id})")
            existing_count += 1
        else:
            # Create experiment with tags
            experiment_id = client.create_experiment(
                name=name,
                tags=config['tags']
            )
            
            # Set description as a tag
            client.set_experiment_tag(
                experiment_id, 
                "mlflow.note.content", 
                config['description']
            )
            
            print(f"✓ Created '{name}' (ID: {experiment_id})")
            created_count += 1
            
    except Exception as e:
        print(f"✗ Failed to create '{name}': {e}")
        sys.exit(1)

print("=" * 60)
print(f"Summary: {created_count} created, {existing_count} already existed")
print("")

# List all experiments
print("All Experiments:")
print("=" * 60)
all_experiments = client.search_experiments(max_results=100)
for exp in all_experiments:
    env_tag = exp.tags.get('environment', 'N/A')
    purpose_tag = exp.tags.get('purpose', 'N/A')
    print(f"  [{exp.experiment_id}] {exp.name}")
    print(f"      Environment: {env_tag}, Purpose: {purpose_tag}")
    
print("=" * 60)
print(f"Total: {len(all_experiments)} experiments")
print("")
print("✅ Custom experiments ready!")

EOFPYTHON
EOF

echo ""
echo "✅ Experiment creation complete!"
echo ""
echo "You can now use these experiments:"
echo "  - production-models: For production deployments"
echo "  - staging-models: For pre-production evaluation"
echo "  - development-models: For experimentation"
echo "  - dataset-registry: For dataset versioning"
echo "  - model-registry-experiments: For registered models"
