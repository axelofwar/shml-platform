#!/usr/bin/env python3
"""
Production-Grade Resource Manager for ML Platform
Dynamically adjusts Docker Compose resource limits based on actual system availability
"""

import psutil
import yaml
import json
import sys
import os
from pathlib import Path
from typing import Dict, Any, Tuple
import subprocess


class ResourceManager:
    """Manages resource allocation for Docker Compose services"""
    
    # Minimum resources required for each service (safety margins)
    MIN_REQUIREMENTS = {
        'traefik': {'cpus': 0.25, 'memory_mb': 128},
        'redis': {'cpus': 0.1, 'memory_mb': 128},
        'node-exporter': {'cpus': 0.05, 'memory_mb': 32},
        'cadvisor': {'cpus': 0.1, 'memory_mb': 64},
        'mlflow-postgres': {'cpus': 0.25, 'memory_mb': 256},
        'mlflow-server': {'cpus': 0.5, 'memory_mb': 512},
        'mlflow-nginx': {'cpus': 0.1, 'memory_mb': 64},
        'mlflow-api': {'cpus': 0.25, 'memory_mb': 256},
        'mlflow-prometheus': {'cpus': 0.1, 'memory_mb': 128},
        'mlflow-grafana': {'cpus': 0.1, 'memory_mb': 128},
        'mlflow-adminer': {'cpus': 0.05, 'memory_mb': 64},
        'mlflow-backup': {'cpus': 0.1, 'memory_mb': 128},
        'ray-postgres': {'cpus': 0.25, 'memory_mb': 256},
        'ray-head': {'cpus': 1.0, 'memory_mb': 2048},
        'ray-compute-api': {'cpus': 0.25, 'memory_mb': 512},
        'ray-prometheus': {'cpus': 0.1, 'memory_mb': 128},
        'ray-grafana': {'cpus': 0.1, 'memory_mb': 128},
        'authentik-db': {'cpus': 0.1, 'memory_mb': 128},
        'authentik-redis': {'cpus': 0.05, 'memory_mb': 64},
        'authentik-server': {'cpus': 0.25, 'memory_mb': 256},
        'authentik-worker': {'cpus': 0.1, 'memory_mb': 128},
    }
    
    # Priority levels (higher = more critical)
    PRIORITY = {
        'critical': 10,  # Database, Redis, Traefik
        'high': 8,       # Core services (MLflow, Ray head)
        'medium': 5,     # API services, monitoring
        'low': 3,        # Backup, admin tools
    }
    
    SERVICE_PRIORITIES = {
        'traefik': 'critical',
        'redis': 'critical',
        'mlflow-postgres': 'critical',
        'ray-postgres': 'critical',
        'mlflow-server': 'high',
        'ray-head': 'high',
        'mlflow-api': 'medium',
        'ray-compute-api': 'medium',
        'mlflow-nginx': 'medium',
        'mlflow-prometheus': 'medium',
        'mlflow-grafana': 'medium',
        'ray-prometheus': 'medium',
        'ray-grafana': 'medium',
        'node-exporter': 'low',
        'cadvisor': 'low',
        'mlflow-adminer': 'low',
        'mlflow-backup': 'low',
        'authentik-db': 'medium',
        'authentik-redis': 'medium',
        'authentik-server': 'medium',
        'authentik-worker': 'low',
    }
    
    def __init__(self, compose_file: str = 'docker-compose.yml'):
        self.compose_file = Path(compose_file)
        if not self.compose_file.exists():
            raise FileNotFoundError(f"Docker Compose file not found: {compose_file}")
        
        self.backup_file = self.compose_file.with_suffix('.yml.backup.resource-manager')
    
    def get_system_resources(self) -> Dict[str, float]:
        """Get available system resources with safety margin"""
        cpu_count = psutil.cpu_count()
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        # Reserve 20% for host system
        available_cpus = cpu_count * 0.80
        available_memory_gb = (memory.available * 0.80) / (1024**3)
        
        # Check if swap is being used (warning sign)
        swap_used_percent = swap.percent
        
        return {
            'total_cpus': cpu_count,
            'available_cpus': available_cpus,
            'total_memory_gb': memory.total / (1024**3),
            'available_memory_gb': available_memory_gb,
            'memory_used_percent': memory.percent,
            'swap_used_percent': swap_used_percent,
            'warning': swap_used_percent > 10 or memory.percent > 85
        }
    
    def load_compose(self) -> Dict[str, Any]:
        """Load Docker Compose configuration"""
        with open(self.compose_file, 'r') as f:
            return yaml.safe_load(f)
    
    def save_compose(self, config: Dict[str, Any]):
        """Save Docker Compose configuration with backup"""
        # Create backup
        if self.compose_file.exists():
            with open(self.backup_file, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        
        # Save new configuration
        with open(self.compose_file, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    def calculate_allocations(self, system_resources: Dict[str, float], 
                            current_config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Calculate optimal resource allocations"""
        
        available_cpus = system_resources['available_cpus']
        available_memory_gb = system_resources['available_memory_gb']
        
        services = current_config.get('services', {})
        allocations = {}
        
        # Calculate minimum requirements
        min_cpu_total = 0
        min_memory_total_gb = 0
        
        for service_name in services.keys():
            min_req = self.MIN_REQUIREMENTS.get(service_name, {'cpus': 0.1, 'memory_mb': 128})
            min_cpu_total += min_req['cpus']
            min_memory_total_gb += min_req['memory_mb'] / 1024
        
        # Check if we can meet minimum requirements
        if min_cpu_total > available_cpus:
            raise RuntimeError(
                f"Insufficient CPU resources! Need at least {min_cpu_total:.2f} CPUs, "
                f"but only {available_cpus:.2f} available"
            )
        
        if min_memory_total_gb > available_memory_gb:
            raise RuntimeError(
                f"Insufficient memory! Need at least {min_memory_total_gb:.2f}GB, "
                f"but only {available_memory_gb:.2f}GB available"
            )
        
        # Calculate CPU and memory budgets after minimum allocations
        remaining_cpus = available_cpus - min_cpu_total
        remaining_memory_gb = available_memory_gb - min_memory_total_gb
        
        # Calculate priority weights
        priority_weights = {}
        total_weight = 0
        for service_name in services.keys():
            priority = self.SERVICE_PRIORITIES.get(service_name, 'low')
            weight = self.PRIORITY[priority]
            priority_weights[service_name] = weight
            total_weight += weight
        
        # Allocate resources
        for service_name in services.keys():
            min_req = self.MIN_REQUIREMENTS.get(service_name, {'cpus': 0.1, 'memory_mb': 128})
            weight = priority_weights[service_name]
            weight_ratio = weight / total_weight
            
            # Base allocation = minimum + proportional share of remaining
            cpu_allocation = min_req['cpus'] + (remaining_cpus * weight_ratio)
            memory_mb = min_req['memory_mb'] + (remaining_memory_gb * 1024 * weight_ratio)
            
            # Apply limits based on service type
            if 'ray-head' in service_name:
                # Ray head needs more resources
                cpu_allocation = min(cpu_allocation, available_cpus * 0.4)
                memory_mb = min(memory_mb, available_memory_gb * 1024 * 0.4)
            elif 'server' in service_name or 'mlflow' in service_name:
                cpu_allocation = min(cpu_allocation, available_cpus * 0.2)
                memory_mb = min(memory_mb, available_memory_gb * 1024 * 0.15)
            elif 'postgres' in service_name:
                cpu_allocation = min(cpu_allocation, 2.0)
                memory_mb = min(memory_mb, 2048)
            
            allocations[service_name] = {
                'cpus_limit': round(cpu_allocation, 2),
                'cpus_reservation': round(min_req['cpus'], 2),
                'memory_limit': self._format_memory(memory_mb),
                'memory_reservation': self._format_memory(min_req['memory_mb'])
            }
        
        return allocations
    
    def _format_memory(self, mb: float) -> str:
        """Format memory value"""
        if mb >= 1024:
            return f"{int(mb / 1024)}G"
        return f"{int(mb)}M"
    
    def apply_allocations(self, config: Dict[str, Any], 
                         allocations: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Apply resource allocations to Docker Compose config"""
        
        for service_name, allocation in allocations.items():
            if service_name in config['services']:
                service = config['services'][service_name]
                
                # Ensure deploy.resources structure exists
                if 'deploy' not in service:
                    service['deploy'] = {}
                if 'resources' not in service['deploy']:
                    service['deploy']['resources'] = {}
                if 'limits' not in service['deploy']['resources']:
                    service['deploy']['resources']['limits'] = {}
                if 'reservations' not in service['deploy']['resources']:
                    service['deploy']['resources']['reservations'] = {}
                
                # Apply allocations
                service['deploy']['resources']['limits']['cpus'] = str(allocation['cpus_limit'])
                service['deploy']['resources']['limits']['memory'] = allocation['memory_limit']
                service['deploy']['resources']['reservations']['cpus'] = str(allocation['cpus_reservation'])
                service['deploy']['resources']['reservations']['memory'] = allocation['memory_reservation']
        
        return config
    
    def generate_report(self, system_resources: Dict[str, float], 
                       allocations: Dict[str, Dict[str, Any]]) -> str:
        """Generate resource allocation report"""
        
        lines = []
        lines.append("=" * 80)
        lines.append("ML Platform Resource Allocation Report")
        lines.append("=" * 80)
        lines.append("")
        
        # System resources
        lines.append("System Resources:")
        lines.append(f"  Total CPUs:           {system_resources['total_cpus']}")
        lines.append(f"  Available CPUs:       {system_resources['available_cpus']:.2f} (80% of total)")
        lines.append(f"  Total Memory:         {system_resources['total_memory_gb']:.2f}GB")
        lines.append(f"  Available Memory:     {system_resources['available_memory_gb']:.2f}GB (80% of available)")
        lines.append(f"  Memory Usage:         {system_resources['memory_used_percent']:.1f}%")
        lines.append(f"  Swap Usage:           {system_resources['swap_used_percent']:.1f}%")
        
        if system_resources['warning']:
            lines.append("")
            lines.append("  ⚠️  WARNING: High memory usage or swap detected!")
            lines.append("  Consider reducing services or adding more RAM")
        
        lines.append("")
        lines.append("=" * 80)
        lines.append("Service Resource Allocations:")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"{'Service':<25} {'CPU Limit':<12} {'CPU Reserve':<12} {'Mem Limit':<12} {'Mem Reserve':<12}")
        lines.append("-" * 80)
        
        # Sort by priority
        sorted_services = sorted(
            allocations.items(),
            key=lambda x: self.PRIORITY[self.SERVICE_PRIORITIES.get(x[0], 'low')],
            reverse=True
        )
        
        total_cpu_limits = 0
        total_cpu_reserves = 0
        
        for service_name, allocation in sorted_services:
            priority = self.SERVICE_PRIORITIES.get(service_name, 'low')
            priority_indicator = {
                'critical': '🔴',
                'high': '🟠',
                'medium': '🟡',
                'low': '🟢'
            }.get(priority, '')
            
            lines.append(
                f"{service_name:<25} "
                f"{allocation['cpus_limit']:<12} "
                f"{allocation['cpus_reservation']:<12} "
                f"{allocation['memory_limit']:<12} "
                f"{allocation['memory_reservation']:<12} "
                f"{priority_indicator} {priority}"
            )
            
            total_cpu_limits += float(allocation['cpus_limit'])
            total_cpu_reserves += float(allocation['cpus_reservation'])
        
        lines.append("-" * 80)
        lines.append(f"{'TOTAL':<25} {total_cpu_limits:<12.2f} {total_cpu_reserves:<12.2f}")
        lines.append("")
        
        # Utilization summary
        cpu_utilization = (total_cpu_limits / system_resources['available_cpus']) * 100
        lines.append(f"CPU Utilization:      {cpu_utilization:.1f}% of available")
        lines.append("")
        
        lines.append("=" * 80)
        lines.append("")
        
        return "\n".join(lines)
    
    def run(self, dry_run: bool = False) -> Tuple[bool, str]:
        """Run resource manager"""
        
        try:
            # Get system resources
            print("Analyzing system resources...")
            system_resources = self.get_system_resources()
            
            # Load current configuration
            print("Loading Docker Compose configuration...")
            config = self.load_compose()
            
            # Calculate optimal allocations
            print("Calculating optimal resource allocations...")
            allocations = self.calculate_allocations(system_resources, config)
            
            # Generate report
            report = self.generate_report(system_resources, allocations)
            print(report)
            
            if dry_run:
                print("\n[DRY RUN] No changes were made to docker-compose.yml")
                return True, report
            
            # Apply allocations
            print("\nApplying resource allocations...")
            updated_config = self.apply_allocations(config, allocations)
            
            # Save configuration
            print(f"Saving updated configuration to {self.compose_file}...")
            print(f"Backup saved to {self.backup_file}")
            self.save_compose(updated_config)
            
            print("\n✅ Resource allocation completed successfully!")
            print(f"\nTo apply changes, restart your services:")
            print(f"  cd {self.compose_file.parent} && docker-compose down && docker-compose up -d")
            
            return True, report
            
        except Exception as e:
            error_msg = f"❌ Error: {str(e)}"
            print(error_msg, file=sys.stderr)
            return False, error_msg


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Production-grade resource manager for ML Platform'
    )
    parser.add_argument(
        '--compose-file',
        default='docker-compose.yml',
        help='Path to docker-compose.yml file'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without modifying files'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output report in JSON format'
    )
    
    args = parser.parse_args()
    
    manager = ResourceManager(args.compose_file)
    success, report = manager.run(dry_run=args.dry_run)
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
