"""Run float_log_summary.py once for each requested float serial number."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


DATA_ROOT = Path(r"Z:\bgc\data")
SUMMARY_SCRIPT = Path(__file__).with_name("float_log_summary.py")
BATCH_OUTPUT_ROOT = Path("batch_outputs")


def available_float_folders() -> list[Path]:
    """Find every folder named wn followed by a serial number."""
    return sorted(
        folder for folder in DATA_ROOT.iterdir()
        if folder.is_dir() and re.fullmatch(r"wn\d+", folder.name, re.IGNORECASE)
    )


def main() -> int:
    BATCH_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    failures = 0

    log_folders = available_float_folders()
    if not log_folders:
        print(f"No float folders found under {DATA_ROOT}")
        return 1

    for log_folder in log_folders:
        serial = log_folder.name[2:]
        output_folder = BATCH_OUTPUT_ROOT / serial
        output_folder.mkdir(parents=True, exist_ok=True)

        environment = os.environ.copy()
        environment["FLOAT_LOG_PATH"] = str(log_folder)
        print(f"Running {serial}: {log_folder}")
        result = subprocess.run(
            [sys.executable, str(SUMMARY_SCRIPT)],
            cwd=output_folder,
            env=environment,
            check=False,
        )
        if result.returncode != 0:
            failures += 1
            print(f"Float {serial} failed with exit code {result.returncode}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
