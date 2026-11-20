#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv_runtime"
VENV_PYTHON="$VENV_DIR/bin/python"

if [[ -d /data1 ]]; then
    DATA_ROOT=/data1
elif [[ -d /mnt/z ]]; then
    DATA_ROOT=/mnt/z
elif [[ -d /z ]]; then
    DATA_ROOT=/z
else
    DATA_ROOT='Z:'
fi
: "${S2BGC_DATA_ROOT:=$DATA_ROOT/S2BGC/data}"
: "${S2BGC_OUTPUT_DIR:=$DATA_ROOT/www/bgc/engineering/S2BGC}"
export S2BGC_DATA_ROOT S2BGC_OUTPUT_DIR

if [[ -n "${S2BGC_PYTHON:-}" ]]; then
    PYTHON_CMD="$S2BGC_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD=python
else
    echo "ERROR: No Python interpreter was found on PATH." >&2
    echo "Install Python 3 or set S2BGC_PYTHON." >&2
    exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Creating S2BGC Python virtual environment with $PYTHON_CMD..."
    "$PYTHON_CMD" -m venv "$VENV_DIR" || {
        echo "ERROR: Failed to create the virtual environment." >&2
        exit 1
    }
fi

"$VENV_PYTHON" -m pip install --upgrade pip || exit 1

echo
echo "Virtual environment is ready."
echo "Data root: $S2BGC_DATA_ROOT"
echo "Output directory: $S2BGC_OUTPUT_DIR"
echo "To activate it later, run:"
echo "    source .venv_runtime/bin/activate"
echo
echo "Running the S2BGC engineering report generator..."
cd -- "$SCRIPT_DIR"
"$VENV_PYTHON" run_engineering_for_serials.py
