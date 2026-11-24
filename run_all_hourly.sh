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

if [[ -d /data1 ]]; then
    Z_ROOT=/data1
elif [[ -d /mnt/z ]]; then
    Z_ROOT=/mnt/z
elif [[ -d /z ]]; then
    Z_ROOT=/z
else
    # Git Bash can usually resolve this Windows-style path if the Z: drive is mounted.
    Z_ROOT='Z:'
fi
: "${S2BGC_DATA_ROOT:=$Z_ROOT/S2BGC/data}"
: "${S2BGC_OUTPUT_DIR:=$Z_ROOT/www/bgc/engineering/S2BGC}"
: "${BGC_DATA_ROOT:=$Z_ROOT/bgc/data}"
: "${BGC_ENGINEERING_ROOT:=$Z_ROOT/www/bgc/engineering}"
: "${MISSION_PAPER_OUTPUT_DIR:=$BGC_ENGINEERING_ROOT}"
# The hourly build publishes HTML. Keep it independent of Kaleido/Chrome even
# if an interactive shell or scheduler inherited BGC_WRITE_PNG=1.
BGC_WRITE_PNG=0
export S2BGC_DATA_ROOT S2BGC_OUTPUT_DIR BGC_DATA_ROOT BGC_ENGINEERING_ROOT MISSION_PAPER_OUTPUT_DIR BGC_WRITE_PNG

mkdir -p -- "$LOG_DIR"
if ! mkdir -- "$LOCK_DIR" 2>/dev/null; then
    echo "Another hourly build is already running. Exiting."
    exit 2
fi

cleanup() {
    rmdir -- "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

find_python() {
    local venv_dir="$1"
    if [[ -x "$venv_dir/bin/python" ]]; then
        printf '%s\n' "$venv_dir/bin/python"
    elif [[ -f "$venv_dir/Scripts/python.exe" ]]; then
        printf '%s\n' "$venv_dir/Scripts/python.exe"
    else
        return 1
    fi
}

S2BGC_PYTHON="$(find_python "$S2BGC/.venv_runtime" 2>/dev/null || true)"
PARSER_PYTHON="$(find_python "$PARSER/.venv" 2>/dev/null || true)"
NAVIS_PYTHON="$(find_python "$NAVIS/.venv" 2>/dev/null || true)"

echo "==== Build started $(timestamp) ====" >> "$LOG"

if [[ -z "$S2BGC_PYTHON" ]]; then
    echo "ERROR: S2BGC Python environment not found. Checked: $S2BGC/.venv_runtime/bin/python and $S2BGC/.venv_runtime/Scripts/python.exe" | tee -a "$LOG"
    BUILD_OK=0
fi
if [[ -z "$PARSER_PYTHON" ]]; then
    echo "ERROR: Parser Python environment not found. Checked: $PARSER/.venv/bin/python and $PARSER/.venv/Scripts/python.exe" | tee -a "$LOG"
    BUILD_OK=0
fi
if [[ -z "$NAVIS_PYTHON" ]]; then
    echo "ERROR: Navis Python environment not found. Checked: $NAVIS/.venv/bin/python and $NAVIS/.venv/Scripts/python.exe" | tee -a "$LOG"
    BUILD_OK=0
fi

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

verify_mission_paper_labels() {
    local paper="$NAVIS/analysis_output/mission_analysis/navis_mission_changes_paper.html"
    if [[ ! -f "$paper" ]]; then
        failed "Mission paper HTML was not created: $paper"
        return
    fi
    if ! grep -Fq 'chart-with-axis-labels' "$paper" || \
       ! grep -Fq 'x-axis-label' "$paper" || \
       ! grep -Fq 'y-axis-label' "$paper" || \
       ! grep -Fq 'x-tick-strip' "$paper"; then
        failed "Mission paper HTML is missing axis-label markup: $paper"
        return
    fi
    echo "Verified mission paper axis labels: $paper" | tee -a "$LOG"
}

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
    if (( BUILD_OK == 1 )); then
        verify_mission_paper_labels
    fi

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
