#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD=python
else
    echo "ERROR: Python was not found. Install Python 3 and try again." >&2
    exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Creating parser Python virtual environment..."
    "$PYTHON_CMD" -m venv "$VENV_DIR" || {
        echo "ERROR: Failed to create the virtual environment." >&2
        exit 1
    }
fi

if [[ -z "${BGC_DATA_ROOT:-}" ]]; then
    for candidate in /data1/bgc/data /mnt/z/bgc/data /z/bgc/data 'Z:/bgc/data'; do
        if [[ -d "$candidate" ]]; then
            export BGC_DATA_ROOT="$candidate"
            break
        fi
    done
fi
if [[ -d /data1 ]]; then
    Z_ROOT=/data1
elif [[ -d /mnt/z ]]; then
    Z_ROOT=/mnt/z
elif [[ -d /z ]]; then
    Z_ROOT=/z
else
    Z_ROOT='Z:'
fi
: "${BGC_ENGINEERING_ROOT:=$Z_ROOT/www/bgc/engineering}"
export BGC_ENGINEERING_ROOT

echo
echo "Data root:       ${BGC_DATA_ROOT:-<unset>}"
echo "Engineering root: $BGC_ENGINEERING_ROOT"
if [[ -n "${BGC_DATA_ROOT:-}" && ! -d "$BGC_DATA_ROOT" ]]; then
    echo "WARNING: The configured data path is not available."
    echo "Override BGC_DATA_ROOT with the mounted or UNC-equivalent path."
fi

echo
echo "Virtual environment is ready."
echo "To activate it later, run:"
echo "    source .venv/bin/activate"
echo
echo "To run all float summaries:"
echo "    .venv/bin/python run_float_summaries.py"
