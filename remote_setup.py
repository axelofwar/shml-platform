#!/usr/bin/env python3
"""
Quick setup script for remote MLflow client
Run this on your remote machine to verify connection
"""

import sys

def main():
    try:
        import mlflow
        print("✅ MLflow installed")
    except ImportError:
        print("❌ MLflow not installed. Run: pip install mlflow")
        sys.exit(1)
    
    # Get server IP from user
    print("\n" + "="*60)
    print("MLflow Remote Client Setup")
    print("="*60)
    
    server_ip = input("\nEnter your ML server IP address (e.g., 192.168.1.100): ").strip()
    
    if not server_ip:
        print("❌ No IP provided")
        sys.exit(1)
    
    tracking_uri = f"http://{server_ip}/api/2.0/mlflow"
    
    print(f"\n📡 Testing connection to: {tracking_uri}")
    
    try:
        mlflow.set_tracking_uri(tracking_uri)
        experiments = mlflow.search_experiments()
        
        print(f"\n✅ SUCCESS! Connected to MLflow server")
        print(f"✅ Found {len(experiments)} experiments")
        
        print("\n📋 Available experiments:")
        for exp in experiments[:5]:  # Show first 5
            print(f"   - {exp.name} (ID: {exp.experiment_id})")
        
        print("\n" + "="*60)
        print("🎉 Setup Complete!")
        print("="*60)
        print("\nAdd this to your Python code:")
        print(f'\nimport mlflow')
        print(f'mlflow.set_tracking_uri("{tracking_uri}")')
        
        print("\nOr set environment variable:")
        print(f'\nexport MLFLOW_TRACKING_URI="{tracking_uri}"')
        
    except Exception as e:
        print(f"\n❌ Connection failed: {e}")
        print("\nTroubleshooting:")
        print(f"  1. Verify server IP: {server_ip}")
        print(f"  2. Check server is running: curl http://{server_ip}/health")
        print(f"  3. Check firewall allows port 80")
        print(f"  4. Try from server first: curl http://localhost/api/2.0/mlflow/experiments/get?experiment_id=0")
        sys.exit(1)

if __name__ == "__main__":
    main()
