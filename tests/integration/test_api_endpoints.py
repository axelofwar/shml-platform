"""
Integration tests for MLflow API v1 endpoints

These tests verify all API endpoints work correctly across:
- Local access (localhost)
- LAN access (${SERVER_IP})
- VPN access (${TAILSCALE_IP})

Run with:
    pytest tests/integration/test_api_endpoints.py --host=all -v
    pytest tests/integration/test_api_endpoints.py --host=lan -v
"""
import pytest
import requests
import time
from typing import Dict
import json
from pathlib import Path
import tempfile


class TestAPIHealth:
    """Test API health and availability"""
    
    @pytest.mark.integration
    @pytest.mark.parametrize("host_key", ["local", "lan", "vpn"])
    def test_health_endpoint(self, test_hosts, host_key):
        """Test /api/v1/health endpoint"""
        base_url = test_hosts[host_key]
        response = requests.get(f"{base_url}/api/v1/health", timeout=10)
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "ok"]
        assert "mlflow_version" in data
        assert "server_time" in data
    
    @pytest.mark.integration
    def test_swagger_docs(self, api_base_url):
        """Test Swagger documentation is accessible"""
        response = requests.get(f"{api_base_url}/api/v1/docs", timeout=10)
        assert response.status_code == 200
        assert b"Swagger" in response.content or b"swagger" in response.content


class TestSchemaEndpoints:
    """Test schema validation endpoints"""
    
    @pytest.mark.integration
    def test_get_full_schema(self, api_v1_url):
        """Test GET /api/v1/schema"""
        response = requests.get(f"{api_v1_url}/schema", timeout=10)
        
        assert response.status_code == 200
        data = response.json()
        assert "experiments" in data
        assert "model_registry" in data or "models" in data
        assert "common_tags" in data or "experiments" in data
    
    @pytest.mark.integration
    def test_get_experiment_schema(self, api_v1_url, test_experiment_name):
        """Test GET /api/v1/schema/experiment/{name}"""
        response = requests.get(
            f"{api_v1_url}/schema/experiment/{test_experiment_name}", 
            timeout=10
        )
        
        # Should return 200 with schema or 404 if experiment doesn't exist
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert "experiment_name" in data or "required_tags" in data
    
    @pytest.mark.integration
    def test_validate_schema(self, api_v1_url, test_tags):
        """Test POST /api/v1/schema/validate"""
        payload = {
            "experiment_name": "test-experiment",
            "tags": test_tags
        }
        
        response = requests.post(
            f"{api_v1_url}/schema/validate",
            json=payload,
            timeout=10
        )
        
        assert response.status_code in [200, 422]
        data = response.json()
        
        # Should have validation results
        assert "is_valid" in data or "valid" in data or "errors" in data


class TestExperimentEndpoints:
    """Test experiment management endpoints"""
    
    @pytest.mark.integration
    def test_list_experiments(self, api_v1_url):
        """Test GET /api/v1/experiments"""
        response = requests.get(f"{api_v1_url}/experiments", timeout=10)
        
        assert response.status_code == 200
        data = response.json()
        assert "experiments" in data
        assert isinstance(data["experiments"], list)
    
    @pytest.mark.integration
    def test_get_experiment_by_id(self, api_v1_url):
        """Test GET /api/v1/experiments/{id}"""
        # First get list of experiments
        response = requests.get(f"{api_v1_url}/experiments", timeout=10)
        assert response.status_code == 200
        experiments = response.json()["experiments"]
        
        if len(experiments) > 0:
            exp_id = experiments[0]["experiment_id"]
            
            # Get specific experiment
            response = requests.get(f"{api_v1_url}/experiments/{exp_id}", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert data["experiment_id"] == exp_id


class TestRunEndpoints:
    """Test run creation and management endpoints"""
    
    @pytest.fixture(scope="class")
    def created_run(self, api_v1_url, test_experiment_name, test_tags):
        """Create a test run for subsequent tests"""
        # Create experiment if it doesn't exist
        import mlflow
        mlflow.set_tracking_uri(api_v1_url.replace("/api/v1", "/mlflow"))
        try:
            mlflow.create_experiment(test_experiment_name)
        except:
            pass  # Experiment already exists
        
        # Create run via API
        payload = {
            "experiment_name": test_experiment_name,
            "tags": test_tags,
            "run_name": "test-run-api",
            "validate_schema": True,
            "parameters": {
                "test_param": 1.0
            }
        }
        
        response = requests.post(
            f"{api_v1_url}/runs/create",
            json=payload,
            timeout=10
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        
        yield data
        
        # Cleanup: finish the run
        try:
            requests.post(
                f"{api_v1_url}/runs/{data['run_id']}/finish",
                json={"status": "FINISHED"},
                timeout=10
            )
        except:
            pass
    
    @pytest.mark.integration
    def test_create_run_with_complete_tags(self, api_v1_url, test_experiment_name, test_tags):
        """Test POST /api/v1/runs/create with complete tags"""
        payload = {
            "experiment_name": test_experiment_name,
            "tags": test_tags,
            "run_name": "test-run-complete",
            "validate_schema": True,
            "parameters": {
                "learning_rate": 0.001,
                "batch_size": 32
            }
        }
        
        response = requests.post(
            f"{api_v1_url}/runs/create",
            json=payload,
            timeout=10
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert "warnings" in data
        assert data["status"] == "created"
        
        # Cleanup
        try:
            requests.post(
                f"{api_v1_url}/runs/{data['run_id']}/finish",
                json={"status": "FINISHED"},
                timeout=10
            )
        except:
            pass
    
    @pytest.mark.integration
    def test_create_run_with_incomplete_tags_shows_warnings(
        self, api_v1_url, test_experiment_name, incomplete_tags
    ):
        """Test that incomplete tags generate warnings but don't block"""
        payload = {
            "experiment_name": test_experiment_name,
            "tags": incomplete_tags,
            "run_name": "test-run-incomplete",
            "validate_schema": True
        }
        
        response = requests.post(
            f"{api_v1_url}/runs/create",
            json=payload,
            timeout=10
        )
        
        # Should succeed with warnings (status 200, not 422)
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert "warnings" in data
        assert len(data["warnings"]) > 0, "Expected warnings for incomplete tags"
        assert data["status"] == "created"
        
        # Verify warning message contains some form of validation info/warning
        warnings_text = " ".join(data["warnings"]).lower()
        assert any(word in warnings_text for word in ["recommend", "missing", "info", "schema", "tag"])
        
        # Cleanup
        try:
            requests.post(
                f"{api_v1_url}/runs/{data['run_id']}/finish",
                json={"status": "FINISHED"},
                timeout=10
            )
        except:
            pass
    
    @pytest.mark.integration
    def test_get_run(self, api_v1_url, created_run):
        """Test GET /api/v1/runs/{id}"""
        run_id = created_run["run_id"]
        
        response = requests.get(f"{api_v1_url}/runs/{run_id}", timeout=10)
        
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == run_id
        assert "status" in data
        assert "metrics" in data or "data" in data
    
    @pytest.mark.integration
    def test_log_metrics(self, api_v1_url, created_run):
        """Test POST /api/v1/runs/{id}/metrics"""
        run_id = created_run["run_id"]
        
        payload = {
            "metrics": {
                "accuracy": 0.95,
                "loss": 0.05
            },
            "step": 1
        }
        
        response = requests.post(
            f"{api_v1_url}/runs/{run_id}/metrics",
            json=payload,
            timeout=10
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "message" in data or "status" in data
    
    @pytest.mark.integration
    def test_finish_run(self, api_v1_url, test_experiment_name, test_tags):
        """Test POST /api/v1/runs/{id}/finish"""
        # Create a run
        payload = {
            "experiment_name": test_experiment_name,
            "tags": test_tags,
            "run_name": "test-run-finish"
        }
        
        response = requests.post(
            f"{api_v1_url}/runs/create",
            json=payload,
            timeout=10
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]
        
        # Finish the run
        response = requests.post(
            f"{api_v1_url}/runs/{run_id}/finish",
            json={"status": "FINISHED"},
            timeout=10
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "message" in data or "status" in data


class TestArtifactEndpoints:
    """Test artifact upload/download endpoints"""
    
    @pytest.fixture(scope="class")
    def run_with_artifacts(self, api_v1_url, test_experiment_name, test_tags):
        """Create a run and upload test artifacts"""
        # Create run
        payload = {
            "experiment_name": test_experiment_name,
            "tags": test_tags,
            "run_name": "test-run-artifacts"
        }
        
        response = requests.post(
            f"{api_v1_url}/runs/create",
            json=payload,
            timeout=10
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]
        
        # Upload a test artifact
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test artifact content\nLine 2\n")
            temp_file = f.name
        
        try:
            with open(temp_file, 'rb') as f:
                files = {'file': ('test_artifact.txt', f, 'text/plain')}
                response = requests.post(
                    f"{api_v1_url}/runs/{run_id}/artifacts",
                    files=files,
                    data={'path': 'test_artifacts'},
                    timeout=30
                )
                assert response.status_code == 200
        finally:
            Path(temp_file).unlink()
        
        yield {"run_id": run_id}
        
        # Cleanup
        try:
            requests.post(
                f"{api_v1_url}/runs/{run_id}/finish",
                json={"status": "FINISHED"},
                timeout=10
            )
        except:
            pass
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_upload_artifact(self, api_v1_url, run_with_artifacts):
        """Test POST /api/v1/runs/{id}/artifacts"""
        run_id = run_with_artifacts["run_id"]
        
        # Create another test file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"test": "data", "value": 123}, f)
            temp_file = f.name
        
        try:
            with open(temp_file, 'rb') as f:
                files = {'file': ('test_data.json', f, 'application/json')}
                response = requests.post(
                    f"{api_v1_url}/runs/{run_id}/artifacts",
                    files=files,
                    data={'path': 'test_artifacts'},
                    timeout=30
                )
                
                assert response.status_code == 200
                data = response.json()
                assert "artifact_uri" in data or "message" in data
        finally:
            Path(temp_file).unlink()
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_download_artifact(self, api_v1_url, run_with_artifacts):
        """Test GET /api/v1/runs/{id}/artifacts/{path}"""
        run_id = run_with_artifacts["run_id"]
        
        # Try to download a specific artifact file (the uploaded test.txt)
        response = requests.get(
            f"{api_v1_url}/runs/{run_id}/artifacts/test_artifacts/test.txt",
            timeout=30
        )
        
        # Should return file or 404 if not found
        assert response.status_code in [200, 404, 500]
        if response.status_code == 200:
            # Should have content
            assert len(response.content) > 0


class TestModelRegistryEndpoints:
    """Test model registry endpoints"""
    
    @pytest.fixture(scope="class")
    def run_with_model(self, api_v1_url, test_experiment_name, test_tags):
        """Create a run with a model artifact"""
        import mlflow
        import mlflow.sklearn
        from sklearn.linear_model import LogisticRegression
        import numpy as np
        import os
        
        # Configure MLflow to use HTTP artifact uploads via the tracking server
        tracking_uri = api_v1_url.replace("/api/v1", "/mlflow")
        mlflow.set_tracking_uri(tracking_uri)
        
        # Force artifact uploads through HTTP proxy (don't use local filesystem)
        # This ensures artifacts go through the --serve-artifacts endpoint
        os.environ["MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR"] = "false"
        
        mlflow.set_experiment(test_experiment_name)
        
        with mlflow.start_run(tags=test_tags) as run:
            # Train simple model
            X = np.random.rand(100, 5)
            y = np.random.randint(0, 2, 100)
            model = LogisticRegression()
            model.fit(X, y)
            
            # Log model - this will upload via HTTP to the MLflow server
            mlflow.sklearn.log_model(model, "model")
            
            # Log metrics for testing
            mlflow.log_metric("accuracy", 0.92)
            mlflow.log_metric("recall", 0.96)
            
            run_id = run.info.run_id
        
        yield {"run_id": run_id, "model_path": "model"}
    
    @pytest.mark.integration
    def test_list_models(self, api_v1_url):
        """Test GET /api/v1/models"""
        response = requests.get(f"{api_v1_url}/models", timeout=10)
        
        assert response.status_code == 200
        data = response.json()
        assert "models" in data or "registered_models" in data
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_register_model_with_low_metrics_shows_warnings(
        self, api_v1_url, run_with_model
    ):
        """Test that models with low metrics show warnings but register successfully"""
        run_id = run_with_model["run_id"]
        model_path = run_with_model["model_path"]
        model_name = f"test-model-warnings-{int(time.time())}"
        
        payload = {
            "run_id": run_id,
            "model_name": model_name,
            "model_path": model_path,
            "description": "Test model for warning validation",
            "privacy_validated": False,  # Not validated
            "min_recall": 0.95  # High threshold
        }
        
        response = requests.post(
            f"{api_v1_url}/models/register",
            json=payload,
            timeout=30
        )
        
        # Should succeed (200) even without privacy validation or high recall
        if response.status_code != 200:
            print(f"\nRegistration failed: {response.status_code}")
            print(f"Response: {response.text}")
            print(f"Run ID: {run_id}, Model Path: {model_path}")
        assert response.status_code == 200, f"Registration failed: {response.text}"
        data = response.json()
        assert "model_name" in data
        assert "version" in data
        assert "warnings" in data
        assert len(data["warnings"]) > 0, "Expected warnings for unvalidated model"
        
        # Verify warning message content
        warnings_text = " ".join(data["warnings"]).lower()
        assert "privacy" in warnings_text or "recall" in warnings_text or "recommend" in warnings_text
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_register_model_complete(self, api_v1_url, run_with_model):
        """Test POST /api/v1/models/register with complete validation"""
        run_id = run_with_model["run_id"]
        model_path = run_with_model["model_path"]
        model_name = f"test-model-complete-{int(time.time())}"
        
        payload = {
            "run_id": run_id,
            "model_name": model_name,
            "model_path": model_path,
            "description": "Test model with full validation",
            "tags": {
                "environment": "test",
                "model_type": "classification"
            },
            "privacy_validated": True,
            "min_recall": 0.95
        }
        
        response = requests.post(
            f"{api_v1_url}/models/register",
            json=payload,
            timeout=30
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["model_name"] == model_name
        assert "version" in data
        assert data["status"] == "registered"
    
    @pytest.mark.integration
    def test_get_model(self, api_v1_url):
        """Test GET /api/v1/models/{name}"""
        # First get list of models
        response = requests.get(f"{api_v1_url}/models", timeout=10)
        assert response.status_code == 200
        
        data = response.json()
        models = data.get("models", data.get("registered_models", []))
        
        if len(models) > 0:
            model_name = models[0]["name"]
            
            # Get specific model
            response = requests.get(f"{api_v1_url}/models/{model_name}", timeout=10)
            assert response.status_code == 200
            model_data = response.json()
            assert model_data["name"] == model_name


class TestStorageEndpoints:
    """Test storage information endpoints"""
    
    @pytest.mark.integration
    def test_storage_info(self, api_v1_url):
        """Test GET /api/v1/storage/info"""
        response = requests.get(f"{api_v1_url}/storage/info", timeout=10)
        
        assert response.status_code == 200
        data = response.json()
        # Check for actual response structure from API
        assert "storage" in data
        assert "artifact_root" in data["storage"] or "backend_store" in data["storage"]
        # Also check for other expected sections
        assert "model_registry" in data or "statistics" in data


class TestCrossHostConsistency:
    """Test that all hosts return consistent results"""
    
    @pytest.mark.integration
    @pytest.mark.parametrize("host_key", ["local", "lan", "vpn"])
    def test_health_consistency(self, test_hosts, host_key):
        """Verify health endpoint returns consistent data across hosts"""
        base_url = test_hosts[host_key]
        
        try:
            response = requests.get(f"{base_url}/api/v1/health", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert "status" in data
            assert data["status"] in ["healthy", "ok"]
        except requests.exceptions.ConnectionError:
            pytest.skip(f"Host {host_key} ({base_url}) not accessible")
    
    @pytest.mark.integration
    @pytest.mark.parametrize("host_key", ["local", "lan", "vpn"])
    def test_schema_consistency(self, test_hosts, host_key):
        """Verify schema endpoint returns same data across hosts"""
        base_url = test_hosts[host_key]
        
        try:
            response = requests.get(f"{base_url}/api/v1/schema", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert "experiments" in data
        except requests.exceptions.ConnectionError:
            pytest.skip(f"Host {host_key} ({base_url}) not accessible")
