#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON="$ENV_DIR/bin/python"

echo
echo "WHOI BGC Python environment setup"
echo "Target directory: $SCRIPT_DIR"
echo "Virtual environment: $ENV_DIR"
echo

if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD=python
else
    echo "Python was not found." >&2
    echo "Install Python 3.8 or newer and try again." >&2
    exit 1
fi

"$PYTHON_CMD" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)' || {
    echo "Python 3.8 or newer is required." >&2
    "$PYTHON_CMD" --version
    exit 1
}

if [[ -f "$VENV_PYTHON" ]]; then
    "$VENV_PYTHON" -c 'import sys' >/dev/null 2>&1 || {
        echo "Existing virtual environment is invalid; recreating it..."
        rm -rf -- "$ENV_DIR"
    }
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$ENV_DIR" || {
        echo "Could not create the virtual environment." >&2
        exit 1
    }
else
    echo "Existing virtual environment found; updating it."
fi

cd -- "$SCRIPT_DIR"
echo "Installing Python packages..."
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel || exit 1
"$VENV_PYTHON" -m pip install --upgrade -r requirements.txt || exit 1

echo "Verifying installed packages..."
"$VENV_PYTHON" -c "import pandas, plotly, requests, openpyxl, kaleido; from plotly.colors import sample_colorscale; print('pandas', pandas.__version__); print('plotly', plotly.__version__); print('Turbo colormap:', sample_colorscale('Turbo', [0, 1]))" || exit 1

echo
echo "Setup complete."
echo "To activate this environment:"
echo "    source .venv/bin/activate"
echo "To run the BGC script without activating it:"
echo "    .venv/bin/python bgcwebsite.py"
