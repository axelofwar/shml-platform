#!/usr/bin/env bash
exec "$(dirname "$(readlink -f "$0")")/scripts/deploy/check_platform_status.sh" "$@"
