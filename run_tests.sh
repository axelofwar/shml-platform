#!/usr/bin/env bash
exec "$(dirname "$(readlink -f "$0")")/scripts/deploy/run_tests.sh" "$@"
