#!/bin/bash
cd "$(dirname "$0")"
for f in docker-compose.*.yml; do docker compose -f "$f" up -d; done
echo "✅ Ray started"
