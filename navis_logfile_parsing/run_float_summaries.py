"""Run float_log_summary.py once for each requested float serial number."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


DEFAULT_DATA_ROOTS = (
    Path(r"Z:\bgc\data"),
    Path(r"\\argus\data1\bgc\data"),
)
SUMMARY_SCRIPT = Path(__file__).with_name("float_log_summary.py")
BATCH_OUTPUT_ROOT = Path("batch_outputs")


def run_float_summary(log_folder: Path, data_root: Path) -> tuple[str, int]:
    """Run one float summary in its own output directory."""
    serial = log_folder.name[2:]
    output_folder = BATCH_OUTPUT_ROOT / serial
    output_folder.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    environment["FLOAT_LOG_PATH"] = str(log_folder)
    result = subprocess.run(
        [sys.executable, str(SUMMARY_SCRIPT)],
        cwd=output_folder,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    run_log = output_folder / "float_summary_run.log"
    run_log.write_text(
        (result.stdout or "")
        + ("\n[stderr]\n" + result.stderr if result.stderr else ""),
        encoding="utf-8",
    )
    if result.returncode:
        print(
            f"Float {serial} failed with exit code {result.returncode}; "
            f"see {run_log}",
            flush=True,
        )
    else:
        print(f"Completed {serial}", flush=True)
    return serial, result.returncode


def resolve_data_root(requested: str | None) -> Path:
    """Return a usable data root, honoring an explicit path or environment variable."""
    candidates = [Path(requested)] if requested else [
        Path(os.environ["BGC_DATA_ROOT"])
        if os.environ.get("BGC_DATA_ROOT")
        else candidate
        for candidate in DEFAULT_DATA_ROOTS
    ]
    for candidate in candidates:
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            # A disconnected or inaccessible network location is handled below.
            continue
    searched = ", ".join(str(path) for path in candidates)
    raise SystemExit(
        "Float data folder is unavailable or access was denied. Searched: "
        f"{searched}\n"
        "Connect the Argus share in this Windows session, or run with "
        "BGC_DATA_ROOT=\\\\server\\share\\bgc\\data "
        "(or pass --data-root)."
    )


def available_float_folders(data_root: Path) -> list[Path]:
    """Find every folder named wn followed by a serial number."""
    return sorted(
        folder for folder in data_root.iterdir()
        if folder.is_dir() and re.fullmatch(r"wn\d+", folder.name, re.IGNORECASE)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        help="BGC data folder; overrides BGC_DATA_ROOT and the default Z:/UNC locations",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, int(os.environ.get("BGC_SUMMARY_WORKERS", "4"))),
        help="Number of float summaries to run concurrently (default: 4)",
    )
    args = parser.parse_args()
    data_root = resolve_data_root(args.data_root)
    BATCH_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    log_folders = available_float_folders(data_root)
    if not log_folders:
        print(f"No float folders found under {data_root}")
        return 1

    print(f"Running {len(log_folders)} float summaries with {args.workers} workers")
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_float_summary, log_folder, data_root): log_folder
            for log_folder in log_folders
        }
        for future in as_completed(futures):
            try:
                _, returncode = future.result()
                failures += int(returncode != 0)
            except Exception as exc:
                failures += 1
                print(f"Float summary worker failed: {exc}", flush=True)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
