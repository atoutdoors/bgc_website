"""Run float_log_summary.py once for each requested float serial number."""

from __future__ import annotations

import os
import re
import json
import subprocess
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


if os.name == "nt":
    DEFAULT_DATA_ROOTS = (Path("Z:/bgc/data"), Path(r"\\argus\data1\bgc\data"))
else:
    DEFAULT_DATA_ROOTS = (Path("/data1/bgc/data"), Path("/mnt/z/bgc/data"), Path("/z/bgc/data"))
SUMMARY_SCRIPT = Path(__file__).with_name("float_log_summary.py")
DEFAULT_OUTPUT_ROOT = (
    "Z:/www/bgc/engineering" if os.name == "nt" else "/data1/www/bgc/engineering"
)
BATCH_OUTPUT_ROOT = Path(
    os.environ.get(
        "BGC_SUMMARY_OUTPUT_ROOT",
        os.environ.get("BGC_ENGINEERING_ROOT", DEFAULT_OUTPUT_ROOT),
    )
)
CACHE_PATH = BATCH_OUTPUT_ROOT / ".summary_cache.json"


def log_signature(log_folder: Path) -> dict[str, object]:
    """Return a cheap signature for deciding whether a float needs rebuilding."""
    log_files = [path for path in log_folder.rglob("*.log") if path.is_file()]
    if not log_files:
        return {"count": 0, "latest": "", "mtime_ns": 0, "size": 0}
    latest = max(log_files, key=lambda path: path.stat().st_mtime_ns)
    stat = latest.stat()
    return {
        "count": len(log_files),
        "latest": str(latest.relative_to(log_folder)),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def load_cache() -> dict[str, dict[str, object]]:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def run_float_summary(log_folder: Path) -> tuple[str, int, dict[str, object]]:
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
    return serial, result.returncode, log_signature(log_folder)


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
        "Set BGC_DATA_ROOT to the mounted data directory or pass --data-root."
    )


def available_float_folders(data_root: Path) -> list[Path]:
    """Find every folder named wn followed by a serial number."""
    folders = sorted(
        folder for folder in data_root.iterdir()
        if folder.is_dir() and re.fullmatch(r"wn\d+", folder.name, re.IGNORECASE)
    )
    usable = []
    for folder in folders:
        if any(folder.rglob("*.log")):
            usable.append(folder)
        else:
            print(f"Skipping {folder.name[2:]}: no .log files found", flush=True)
    return usable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        help="BGC data folder; overrides BGC_DATA_ROOT and the default Z:/UNC locations",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, int(os.environ.get("BGC_SUMMARY_WORKERS", "8"))),
        help="Number of float summaries to run concurrently (default: 8)",
    )
    args = parser.parse_args()
    data_root = resolve_data_root(args.data_root)
    BATCH_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    log_folders = available_float_folders(data_root)
    if not log_folders:
        print(f"No float folders found under {data_root}")
        return 1

    cache = load_cache()
    pending: list[tuple[Path, dict[str, object]]] = []
    for log_folder in log_folders:
        serial = log_folder.name[2:]
        signature = log_signature(log_folder)
        report_path = BATCH_OUTPUT_ROOT / serial / "float_health_report.html"
        if cache.get(serial) == signature and report_path.is_file():
            print(f"Skipping unchanged {serial}", flush=True)
        else:
            pending.append((log_folder, signature))

    print(
        f"Running {len(pending)} changed float summaries "
        f"with {args.workers} workers; skipped {len(log_folders) - len(pending)} unchanged",
        flush=True,
    )
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_float_summary, log_folder): (log_folder, signature)
            for log_folder, signature in pending
        }
        for future in as_completed(futures):
            try:
                serial, returncode, signature = future.result()
                failures += int(returncode != 0)
                if returncode == 0:
                    cache[serial] = signature
            except Exception as exc:
                failures += 1
                print(f"Float summary worker failed: {exc}", flush=True)

    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
