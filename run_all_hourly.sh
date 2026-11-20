#!/usr/bin/env bash

set -u

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
S2BGC="$ROOT/S2BGC"
PARSER="$ROOT/navis_logfile_parsing"
NAVIS="$ROOT/navis"
LOG_DIR="$ROOT/logs"
LOG="$LOG_DIR/hourly-build.log"
SUCCESS_STATE="$LOG_DIR/hourly-build-success-streak.txt"
LOCK_DIR="${TMPDIR:-/tmp}/bgc_website_hourly_build.lock"
BUILD_OK=1

: "${S2BGC_DATA_ROOT:=/mnt/z/S2BGC/data}"
: "${S2BGC_OUTPUT_DIR:=/mnt/z/www/bgc/engineering/S2BGC}"
: "${BGC_DATA_ROOT:=/mnt/z/bgc/data}"
: "${BGC_ENGINEERING_ROOT:=/mnt/z/www/bgc/engineering}"
export S2BGC_DATA_ROOT S2BGC_OUTPUT_DIR BGC_DATA_ROOT BGC_ENGINEERING_ROOT

mkdir -p -- "$LOG_DIR"
if ! mkdir -- "$LOCK_DIR" 2>/dev/null; then
    echo "Another hourly build is already running. Exiting."
    exit 2
fi

cleanup() {
    rmdir -- "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

S2BGC_PYTHON="$S2BGC/.venv_runtime/bin/python"
PARSER_PYTHON="$PARSER/.venv/bin/python"
NAVIS_PYTHON="$NAVIS/.venv/bin/python"

if [[ ! -x "$S2BGC_PYTHON" ]]; then
    echo "ERROR: Run S2BGC/setup_s2bgc_venv.sh first."
    BUILD_OK=0
fi
if [[ ! -x "$PARSER_PYTHON" ]]; then
    echo "ERROR: Run navis_logfile_parsing/setup_float_parser_venv.sh first."
    BUILD_OK=0
fi
if [[ ! -x "$NAVIS_PYTHON" ]]; then
    echo "ERROR: Run navis/setup_bgc_environment.sh first."
    BUILD_OK=0
fi

timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

progress() {
    local percent="$1"
    local message="$2"
    local filled=$((percent / 2))
    local bar=""
    printf -v bar '%*s' "$filled" ''
    bar="${bar// /#}"
    printf -v bar '%-50s' "$bar"
    bar="${bar// /-}"
    printf '\r[%s] %3d%% - %s - %s' "$bar" "$percent" "$message" "$(date '+%H:%M:%S')"
}

failed() {
    BUILD_OK=0
    echo "FAILED: $1 $(timestamp)" >> "$LOG"
    echo "FAILED: $1"
}

run_stage() {
    local label="$1"
    shift
    "$@" 2>&1 | tee -a "$LOG"
    local status=${PIPESTATUS[0]}
    if (( status != 0 )); then
        failed "$label"
    fi
}

echo "==== Build started $(timestamp) ====" >> "$LOG"
echo "================================================"
echo "       BGC WEBSITE HOURLY BUILD"
echo "================================================"
echo "Log: $LOG"

if (( BUILD_OK == 1 )); then
    progress 0 "Starting build"
    progress 5 "S2BGC engineering pages"
    run_stage "S2BGC engineering pages" "$S2BGC_PYTHON" "$S2BGC/run_engineering_for_serials.py"

    progress 30 "Navis float summaries"
    run_stage "Navis float summaries" "$PARSER_PYTHON" "$PARSER/run_float_summaries.py" --data-root "$BGC_DATA_ROOT"

    progress 55 "Main BGC website"
    run_stage "Main BGC website" "$NAVIS_PYTHON" -u "$NAVIS/bgcwebsite.py"

    progress 80 "Mission paper HTML"
    run_stage "Mission paper HTML" "$NAVIS_PYTHON" -u "$NAVIS/build_mission_paper_html.py" "$BGC_DATA_ROOT"

    progress 100 "Build stages complete"
    printf '\n'
fi

echo "==== Build finished $(timestamp) ====" >> "$LOG"
if (( BUILD_OK == 1 )); then
    SUCCESS_STREAK=0
    if [[ -f "$SUCCESS_STATE" ]]; then
        read -r SUCCESS_STREAK < "$SUCCESS_STATE" || SUCCESS_STREAK=0
    fi
    SUCCESS_STREAK=$((SUCCESS_STREAK + 1))
    echo "$SUCCESS_STREAK" > "$SUCCESS_STATE"
    if (( SUCCESS_STREAK >= 3 )); then
        : > "$LOG"
        echo "3 consecutive successful builds. Log cleared."
        echo 0 > "$SUCCESS_STATE"
    fi
else
    echo 0 > "$SUCCESS_STATE"
fi

echo "Finished: $(timestamp)"
echo "Details: $LOG"
if (( BUILD_OK == 1 )); then
    exit 0
else
    exit 1
fi
