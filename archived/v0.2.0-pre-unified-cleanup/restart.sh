#!/bin/bash
cd "$(dirname "$0")"
./stop.sh
sleep 2
./start.sh
