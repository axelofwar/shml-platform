#!/usr/bin/env bash
exec "$(dirname "$(readlink -f "$0")")/scripts/deploy/stop_all.sh" "$@"
