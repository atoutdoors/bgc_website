#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/build_mission_paper_html.py"

echo
echo "========================================"
echo "  Navis mission paper builder"
echo "========================================"
echo

echo "[1/4] Mission data folder: ${MISSION_DATA_ROOT:-/mnt/z/bgc/data}"
echo "[1/4] Paper output folder: ${MISSION_PAPER_OUTPUT_DIR:-/mnt/z/www/bgc/engineering}"

if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "[2/4] Python was not found." >&2
    exit 1
fi

echo "[2/4] Python found: $PYTHON"
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)' || {
    echo "Python 3.8 or newer is required." >&2
    "$PYTHON" --version
    exit 1
}

cd -- "$SCRIPT_DIR"
echo "[3/4] Generating mission-analysis CSV files and figures..."
"$PYTHON" -u "$SCRIPT" "$@"
EXIT_CODE=$?

if (( EXIT_CODE == 0 )); then
    echo "[4/4] HTML report generated successfully."
    echo "Output: analysis_output/mission_analysis/navis_mission_changes_paper.html"
else
    echo "[4/4] Mission paper generation failed with exit code $EXIT_CODE." >&2
fi

exit "$EXIT_CODE"
