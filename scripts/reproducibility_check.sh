#!/usr/bin/env sh
# Generate the dataset twice into two temporary folders and compare row counts and SHA-256 checksums
# (docs/07 section 10, acceptance criterion 17, metric M13). macOS / Linux equivalent of the .ps1 script.
# Usage (project root, venv active):  sh scripts/reproducibility_check.sh [seed] [employees] [leave] [expense]
set -eu
SEED="${1:-20261022}"; EMPLOYEES="${2:-400}"; LEAVE="${3:-800}"; EXPENSE="${4:-1000}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
for RUN in run_a run_b; do
  python -m src.data.generate --seed "$SEED" --employees "$EMPLOYEES" --leave-requests "$LEAVE" \
    --expense-claims "$EXPENSE" --out "$WORK/$RUN" > /dev/null
done
python -m src.data.compare_runs "$WORK/run_a" "$WORK/run_b" --report data/validation/reproducibility.json
