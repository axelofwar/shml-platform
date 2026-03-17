#!/bin/bash
# Check Ray cluster status and resources

echo "================================================"
echo "Ray Cluster Status"
echo "================================================"
echo ""

if ! ray status &>/dev/null 2>&1; then
    echo "❌ Ray cluster is not running"
    echo ""
    echo "Start with: ./start_ray_head.sh"
    exit 1
fi

ray status

echo ""
echo "================================================"
echo "GPU Status"
echo "================================================"
echo ""

if nvidia-smi &>/dev/null; then
    nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv
else
    echo "⚠️  nvidia-smi not available"
fi

echo ""
echo "================================================"
echo "System Resources"
echo "================================================"
echo ""

echo "CPU Usage:"
top -bn1 | grep "Cpu(s)" | awk '{print "  "$0}'

echo ""
echo "Memory Usage:"
free -h | grep -E "^Mem|^Swap"

echo ""
echo "Disk Usage:"
df -h / | tail -1

echo ""
echo "Active Ray Jobs:"
python3 -c "
import ray
try:
    ray.init(address='auto', ignore_reinit_error=True)
    from ray.job_submission import JobSubmissionClient
    client = JobSubmissionClient('http://127.0.0.1:8265')
    jobs = client.list_jobs()
    if jobs:
        for job in jobs:
            print(f'  {job.job_id}: {job.status}')
    else:
        print('  No active jobs')
except Exception as e:
    print(f'  Could not fetch jobs: {e}')
" 2>/dev/null || echo "  Could not connect to Ray"

echo ""
