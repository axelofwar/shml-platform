#!/usr/bin/env bash
exec "$(dirname "$(readlink -f "$0")")/scripts/deploy/start_all_dev.sh" "$@"
