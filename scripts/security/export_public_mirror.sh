#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ALLOWLIST_FILE="${REPO_ROOT}/.github/public-mirror-allowlist.txt"
DENYLIST_FILE="${REPO_ROOT}/.github/public-mirror-denylist.txt"
OUTPUT_DIR="${REPO_ROOT}/.public-mirror"
REPORT_FILE=""
DRY_RUN="false"
CLEAN_OUTPUT="true"

usage() {
  cat <<'USAGE'
Usage: bash scripts/security/export_public_mirror.sh [options]

Build a sanitized public mirror workspace from tracked files using:
  - .github/public-mirror-allowlist.txt
  - .github/public-mirror-denylist.txt

Options:
  --output <path>      Output directory (default: .public-mirror)
  --allowlist <path>   Allowlist file path
  --denylist <path>    Denylist file path
  --report <path>      Write summary report to file
  --dry-run            Validate and print summary only (no file export)
  --no-clean           Do not remove output directory before export
  --help               Show this help text
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --allowlist)
      ALLOWLIST_FILE="$2"
      shift 2
      ;;
    --denylist)
      DENYLIST_FILE="$2"
      shift 2
      ;;
    --report)
      REPORT_FILE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --no-clean)
      CLEAN_OUTPUT="false"
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ ! -f "$ALLOWLIST_FILE" ]]; then
  echo "Allowlist not found: $ALLOWLIST_FILE" >&2
  exit 1
fi

if [[ ! -f "$DENYLIST_FILE" ]]; then
  echo "Denylist not found: $DENYLIST_FILE" >&2
  exit 1
fi

TEMP_DIR="$(mktemp -d)"
SELECTED_FILE_LIST="${TEMP_DIR}/selected.txt"
DENIED_FILE_LIST="${TEMP_DIR}/denied.txt"
NONALLOWED_FILE_LIST="${TEMP_DIR}/nonallowed.txt"
TRACKED_FILE_LIST="${TEMP_DIR}/tracked.txt"

cleanup() {
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

git -C "$REPO_ROOT" ls-files > "$TRACKED_FILE_LIST"

python3 - "$ALLOWLIST_FILE" "$DENYLIST_FILE" "$SELECTED_FILE_LIST" "$DENIED_FILE_LIST" "$NONALLOWED_FILE_LIST" "$TRACKED_FILE_LIST" <<'PY'
import fnmatch
import sys
from pathlib import Path

allowlist_path = Path(sys.argv[1])
denylist_path = Path(sys.argv[2])
selected_output = Path(sys.argv[3])
denied_output = Path(sys.argv[4])
nonallowed_output = Path(sys.argv[5])
tracked_file_list = Path(sys.argv[6])


def load_patterns(path: Path):
    patterns = []
    for line in path.read_text().splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith('#'):
            continue
        patterns.append(candidate)
    return patterns


allow_patterns = load_patterns(allowlist_path)
deny_patterns = load_patterns(denylist_path)

tracked_files = [line.strip() for line in tracked_file_list.read_text().splitlines() if line.strip()]

selected = []
denied = []
nonallowed = []

for relative_path in tracked_files:
    if any(fnmatch.fnmatch(relative_path, pattern) for pattern in deny_patterns):
        denied.append(relative_path)
        continue
    if any(fnmatch.fnmatch(relative_path, pattern) for pattern in allow_patterns):
        selected.append(relative_path)
    else:
        nonallowed.append(relative_path)

selected_output.write_text('\n'.join(selected) + ('\n' if selected else ''))
denied_output.write_text('\n'.join(denied) + ('\n' if denied else ''))
nonallowed_output.write_text('\n'.join(nonallowed) + ('\n' if nonallowed else ''))
PY

selected_count=$(wc -l < "$SELECTED_FILE_LIST" | tr -d ' ')
denied_count=$(wc -l < "$DENIED_FILE_LIST" | tr -d ' ')
nonallowed_count=$(wc -l < "$NONALLOWED_FILE_LIST" | tr -d ' ')

if [[ "$selected_count" -eq 0 ]]; then
  echo "No files selected for public mirror export. Check allowlist patterns." >&2
  exit 1
fi

summary=$(cat <<EOF
Public mirror export summary:
  Selected files: ${selected_count}
  Source denylist matches (excluded): ${denied_count}
  Source non-allowlisted files (excluded): ${nonallowed_count}
EOF
)

echo "$summary"

if [[ -n "$REPORT_FILE" ]]; then
  mkdir -p "$(dirname "$REPORT_FILE")"
  {
    echo "$summary"
    echo
    echo "First 50 source denylist matches:"
    head -50 "$DENIED_FILE_LIST" || true
    echo
    echo "First 50 source non-allowlisted files:"
    head -50 "$NONALLOWED_FILE_LIST" || true
  } > "$REPORT_FILE"
fi

if [[ "$DRY_RUN" == "true" ]]; then
  exit 0
fi

if [[ "$CLEAN_OUTPUT" == "true" && -d "$OUTPUT_DIR" ]]; then
  rm -rf "$OUTPUT_DIR"
fi

mkdir -p "$OUTPUT_DIR"

while IFS= read -r relative_path; do
  [[ -z "$relative_path" ]] && continue
  source_path="${REPO_ROOT}/${relative_path}"
  destination_path="${OUTPUT_DIR}/${relative_path}"
  mkdir -p "$(dirname "$destination_path")"
  cp -a "$source_path" "$destination_path"
done < "$SELECTED_FILE_LIST"

OUTPUT_FILE_LIST="${TEMP_DIR}/output-files.txt"
find "$OUTPUT_DIR" -type f | sed "s#^${OUTPUT_DIR}/##" > "$OUTPUT_FILE_LIST"

python3 - "$DENYLIST_FILE" "$OUTPUT_FILE_LIST" <<'PY'
import fnmatch
import sys
from pathlib import Path

denylist_path = Path(sys.argv[1])
output_file_list = Path(sys.argv[2])
deny_patterns = []
for line in denylist_path.read_text().splitlines():
    candidate = line.strip()
    if not candidate or candidate.startswith('#'):
        continue
    deny_patterns.append(candidate)

violations = []
for rel_file in [line.strip() for line in output_file_list.read_text().splitlines() if line.strip()]:
    if any(fnmatch.fnmatch(rel_file, pattern) for pattern in deny_patterns):
        violations.append(rel_file)

if violations:
    print('Export contains denylisted files:', file=sys.stderr)
    for rel_file in violations:
        print(f'  - {rel_file}', file=sys.stderr)
    sys.exit(1)
PY

echo "Public mirror export complete: ${OUTPUT_DIR}"
