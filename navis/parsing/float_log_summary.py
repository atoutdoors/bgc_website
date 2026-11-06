#!/usr/bin/env python3
"""Read every .log file under LOG_PATH and summarize each float."""

from __future__ import annotations

import html
import json
import os
import re
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


# Folder containing the log files. All *.log files below this folder are read.
LOG_PATH = Path(os.environ.get("FLOAT_LOG_PATH", r"Z:\bgc\data\wn1665"))
HTML_OUTPUT = Path("float_health_report.html")
PARK_PLOT_OUTPUT = Path("park_pressure_plot.html")
VELOCITY_PLOT_OUTPUT = Path("vertical_velocity_plot.html")
PARK_OVERLAY_OUTPUT = Path("park_pressure_overlay.html")
VELOCITY_OVERLAY_OUTPUT = Path("vertical_velocity_overlay.html")
MISSION_JSON_OUTPUT = Path("mission.json")
# Set True to skip log parsing and generate only mission.json.
MISSION_ONLY = True

# Set True to save each float's plots in its matching engineering folder.
SAVE_PLOTS_TO_FLOAT_FOLDER = True
ENGINEERING_ROOT = Path(r"\\argus\data1\www\bgc\engineering")
# Set False to generate files without opening browser windows.
OPEN_WINDOWS = False
# Approximate seawater conversion: 1 dbar/s = 99.4 cm/s.
DBAR_PER_SECOND_TO_CM_PER_SECOND = 99.4

LINE_RE = re.compile(
    r"^\((?P<date>[^,]+),\s*(?P<seconds>[0-9.]+)\s+sec\)\s+"
    r"(?P<event>\S+?\(\))\s*(?P<message>.*)$"
)
PROFILE_RE = re.compile(
    r"Profile\s+(?P<profile>\d+)\.\s+\((?P<name>[^ ]+)"
    r".*?FwRev:\s*(?P<fw>[^)]+)\)"
)
PRF_ID_RE = re.compile(r"PrfId\s*:\s*(?P<profile>\d+)", re.IGNORECASE)
FIX_RE = re.compile(
    r"Fix:\s+(?P<lon>-?\d+(?:\.\d+)?)\s+"
    r"(?P<lat>-?\d+(?:\.\d+)?)\s+\d{2}/\d{2}/\d{4}\s+"
    r"\d{6}\s+(?P<sat>\d+)"
)
BATTERY_RE = re.compile(
    r"Battery Min/Avg/Max \[[^]]+,\s*"
    r"(?P<min>[\d.]+)/(?P<avg>[\d.]+)/(?P<max>[\d.]+)V\]"
)
CURRENT_RE = re.compile(
    r"Current Min/Avg/Max \[[^]]+,\s*"
    r"(?P<min>[\d.]+)/(?P<avg>[\d.]+)/(?P<max>[\d.]+) mA\]"
)
BARO_RE = re.compile(r"Barometer \[[^]]+,\s*(?P<pressure>[\d.]+)\"Hg\]")
PARK_PRESSURE_RE = re.compile(
    r"(?:ParkPOutOfBand\[[^,]+,\s*|Pressure:\s*)(?P<pressure>-?[\d.]+)\s*(?:d?bars?)?",
    re.IGNORECASE,
)
PROFILE_PRESSURE_RE = re.compile(r"(?:Pressure:\s*|PTS:\s*)(?P<pressure>-?[\d.]+)\s*d?bars?", re.IGNORECASE)
VELOCITY_RE = re.compile(
    r"(?:(?:Velocity|Speed|Vel)\s*:?\s*|(?<![A-Za-z])v\s*=\s*)"
    r"(?P<values>-?[\d.]+(?:\s*[/,]\s*-?[\d.]+){0,2})\s*(?P<unit>[A-Za-z/]+)?",
    re.IGNORECASE,
)
VELOCITY_PRESSURE_RE = re.compile(r"\bP\s*=\s*(?P<pressure>-?[\d.]+)\s*d?bars?", re.IGNORECASE)
HUMIDITY_RE = re.compile(
    r"(?:Humidity|Hum)\s*:?\s*"
    r"(?P<values>-?[\d.]+(?:\s*[/,]\s*-?[\d.]+){0,2})",
    re.IGNORECASE,
)

FIELDS = [
    "serial_number", "log_files", "log_records", "first_seen_utc", "last_seen_utc",
    "duration_days", "profile", "instrument", "firmware", "gps_fixes",
    "gps_satellites_min_avg_max", "last_longitude", "last_latitude",
    "battery_min_avg_max_v", "current_min_avg_max_ma", "velocity_recorded",
    "velocity_last_timestamp_utc", "humidity_min_avg_max",
    "humidity_recorded", "humidity_last_timestamp_utc",
    "barometer_last_inhg",
    "login_successes", "connections_established", "transfer_failures",
    "warnings_errors", "notable_events",
]


def empty_summary(serial: str) -> dict[str, object]:
    count_fields = {"log_files", "log_records", "gps_fixes", "login_successes",
                    "connections_established", "transfer_failures", "warnings_errors"}
    return {field: (serial if field == "serial_number" else 0 if field in count_fields else "")
            for field in FIELDS}


def serial_from_filename(path: Path) -> str:
    """Extract 1200 from a filename such as 1200.007.log."""
    normalized_name = re.sub(r"\.partial(?=\.log$)", "", path.name, flags=re.IGNORECASE)
    match = re.match(r"([A-Za-z0-9-]+)\.\d+\.log$", normalized_name, re.IGNORECASE)
    return match.group(1) if match else path.stem.split(".")[0]


def is_partial_log(path: Path) -> bool:
    return "partial" in path.name.lower()


def add_range(summary: dict[str, object], field: str, values: list[float]) -> None:
    if values:
        summary[field] = "/".join(f"{value:.1f}" for value in values)


def metric_values(match: re.Match[str]) -> list[float]:
    return [float(value) for value in re.findall(r"-?[\d.]+", match["values"])]


def scalar_value(value: str) -> object:
    value = value.strip()
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.lower() in {"null", "none", "nan"}:
        return None
    try:
        return float(value) if any(character in value for character in ".eE") else int(value)
    except ValueError:
        return value


def parse_mission_file(path: Path) -> dict[str, object]:
    """Convert a JSON, JSON-lines, or key/value .msg file into JSON data."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        contents = json.loads(text)
    except json.JSONDecodeError:
        records = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Mission configuration lines are prefixed with "$" and may have
            # a unit annotation after the value, such as "[sec]".
            stripped = stripped.lstrip("$ ").strip()
            if not stripped:
                continue
            stop_after_verbosity = re.search(r"\bVerbosity\b", stripped, re.IGNORECASE) is not None
            try:
                records.append(json.loads(stripped))
                if stop_after_verbosity:
                    break
                continue
            except json.JSONDecodeError:
                pass
            parenthesized = re.match(r"^([A-Za-z_][\w.-]*)\((.*?)\)", stripped)
            if parenthesized:
                key = parenthesized.group(1).strip()
                value = parenthesized.group(2).strip()
                records.append({key: scalar_value(value)})
            elif "=" in stripped:
                key, value = stripped.split("=", 1)
                records.append({key.strip(): scalar_value(value)})
            elif ":" in stripped:
                key, value = stripped.split(":", 1)
                records.append({key.strip(): scalar_value(value)})
            if stop_after_verbosity:
                break
        contents = records
    return {
        "source_file": str(path),
        "source_modified_utc": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "mission": contents,
    }


def write_latest_mission_json(output_path: Path) -> None:
    msg_files = list(LOG_PATH.rglob("*.msg"))
    if not msg_files:
        print(f"No .msg mission file found below {LOG_PATH}")
        return
    latest = max(msg_files, key=lambda path: path.stat().st_mtime)
    output_path.write_text(json.dumps(parse_mission_file(latest), indent=2), encoding="utf-8")
    mission_path = output_path.resolve()
    print(f"Wrote {mission_path} from {latest}")
    if OPEN_WINDOWS:
        webbrowser.open_new(mission_path.as_uri())


def save_latest_mission() -> None:
    write_latest_mission_json(MISSION_JSON_OUTPUT)


def parse_log(path: Path, summary: dict[str, object]) -> None:
    summary["log_files"] += 1
    battery_values: list[float] = []
    current_values: list[float] = []
    velocity_values: list[float] = []
    humidity_values: list[float] = []
    velocity_readings: list[str] = []
    humidity_readings: list[str] = []
    satellite_values: list[int] = []
    notable: set[str] = set()
    park_active = False
    summary.setdefault("park_pressure_points", [])

    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = LINE_RE.match(raw_line)
        if not match:
            continue

        summary["log_records"] += 1
        timestamp = datetime.strptime(
            match["date"], "%b %d %Y %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
        iso = timestamp.isoformat()
        if not summary["first_seen_utc"] or iso < summary["first_seen_utc"]:
            summary["first_seen_utc"] = iso
        if not summary["last_seen_utc"] or iso > summary["last_seen_utc"]:
            summary["last_seen_utc"] = iso

        message = match["message"]
        lower = message.lower()
        event = match["event"].lower()

        if "parkinit()" in lower or "park profile" in lower and "initiated" in lower:
            park_active = True
        # Some logs begin after ParkInit(), so accept explicit Park() pressure
        # lines even when the start marker is not present in that file.
        is_explicit_park_pressure = "parkpoutofband" in lower or event == "park()"
        if park_active or is_explicit_park_pressure:
            if pressure := PARK_PRESSURE_RE.search(message):
                summary["park_pressure_points"].append((iso, float(pressure["pressure"])))
        # Include the park pressure recorded at the start/end of each profile.
        if event in {"profileinit()", "parkterminate()"}:
            if pressure := PROFILE_PRESSURE_RE.search(message):
                summary["park_pressure_points"].append((iso, float(pressure["pressure"])))
        # Include the final low-pressure reading recorded when the float
        # reaches the surface after the park/profile cycle.
        if event == "surfacedetect()":
            if pressure := PARK_PRESSURE_RE.search(message):
                summary["park_pressure_points"].append((iso, float(pressure["pressure"])))
        if "parkterminate()" in lower:
            park_active = False

        if profile := PROFILE_RE.search(message):
            summary["profile"] = profile["profile"]
            summary["instrument"] = profile["name"]
            summary["firmware"] = profile["fw"].strip()
        if prf_id := PRF_ID_RE.search(message):
            summary["profile"] = prf_id["profile"]
        if fix := FIX_RE.search(message):
            summary["gps_fixes"] += 1
            summary["last_longitude"] = fix["lon"]
            summary["last_latitude"] = fix["lat"]
            satellite_values.append(int(fix["sat"]))
        if battery := BATTERY_RE.search(message):
            battery_values = [float(battery[key]) for key in ("min", "avg", "max")]
        if current := CURRENT_RE.search(message):
            current_values = [float(current[key]) for key in ("min", "avg", "max")]
        if velocity := VELOCITY_RE.search(message):
            values = metric_values(velocity)
            velocity_values.extend(values)
            unit = f" {velocity['unit']}" if velocity['unit'] else ""
            velocity_readings.append(f"{iso}: {', '.join(f'{value:g}' for value in values)}{unit}")
            summary.setdefault("velocity_points", [])
            if velocity_pressure := VELOCITY_PRESSURE_RE.search(message):
                pressure_value = float(velocity_pressure["pressure"])
                summary["velocity_points"].extend(
                    (pressure_value, value * DBAR_PER_SECOND_TO_CM_PER_SECOND)
                    for value in values
                )
            summary["velocity_last_timestamp_utc"] = iso
        if humidity := HUMIDITY_RE.search(message):
            values = metric_values(humidity)
            humidity_values.extend(values)
            humidity_readings.append(f"{iso}: {', '.join(f'{value:g}' for value in values)}")
            summary["humidity_last_timestamp_utc"] = iso
        if barometer := BARO_RE.search(message):
            summary["barometer_last_inhg"] = barometer["pressure"]

        if "login successful" in lower:
            summary["login_successes"] += 1
        if "connection " in lower and " established" in lower:
            summary["connections_established"] += 1
        if any(text in lower for text in ("download failed", "transfer aborted", "packet timeout")):
            summary["transfer_failures"] += 1
        if any(text in lower for text in ("error", "failed", "failure", "timeout", "abort", "warning")):
            summary["warnings_errors"] += 1

        for label, text in (
            ("GPS fix", "gps fix obtained"),
            ("mission download failure", "download failed"),
            ("packet timeout", "packet timeout"),
            ("vitals upload", "uploading"),
        ):
            if text in lower:
                notable.add(label)

    add_range(summary, "battery_min_avg_max_v", battery_values)
    add_range(summary, "current_min_avg_max_ma", current_values)
    add_range(summary, "humidity_min_avg_max", humidity_values)
    summary["velocity_recorded"] = "; ".join(velocity_readings)
    summary["humidity_recorded"] = "; ".join(humidity_readings)
    if satellite_values:
        summary["gps_satellites_min_avg_max"] = (
            f"{min(satellite_values)}/{sum(satellite_values) / len(satellite_values):.1f}/"
            f"{max(satellite_values)}"
        )
    summary["notable_events"] = ", ".join(sorted(notable))


def finish_summary(summary: dict[str, object]) -> None:
    if summary["first_seen_utc"] and summary["last_seen_utc"]:
        start = datetime.fromisoformat(summary["first_seen_utc"])
        end = datetime.fromisoformat(summary["last_seen_utc"])
        summary["duration_days"] = f"{(end - start).total_seconds() / 86400:.2f}"


def merge_summary(total: dict[str, object], current: dict[str, object]) -> None:
    """Combine multiple log files for the same float/profile row."""
    count_fields = ("log_files", "log_records", "gps_fixes", "login_successes",
                    "connections_established", "transfer_failures", "warnings_errors")
    for field in count_fields:
        total[field] += current[field]
    if current["first_seen_utc"] and (not total["first_seen_utc"] or current["first_seen_utc"] < total["first_seen_utc"]):
        total["first_seen_utc"] = current["first_seen_utc"]
    if current["last_seen_utc"] and (not total["last_seen_utc"] or current["last_seen_utc"] > total["last_seen_utc"]):
        total["last_seen_utc"] = current["last_seen_utc"]
    for field in ("instrument", "firmware", "gps_satellites_min_avg_max", "last_longitude",
                  "last_latitude", "battery_min_avg_max_v", "current_min_avg_max_ma",
                  "velocity_last_timestamp_utc", "humidity_min_avg_max",
                  "humidity_last_timestamp_utc", "barometer_last_inhg"):
        if current[field]:
            total[field] = current[field]
    for field in ("velocity_recorded", "humidity_recorded"):
        if current[field]:
            total[field] = "; ".join(filter(None, (str(total[field]), str(current[field]))))
    total.setdefault("park_pressure_points", [])
    total["park_pressure_points"].extend(current.get("park_pressure_points", []))
    total.setdefault("velocity_points", [])
    total["velocity_points"].extend(current.get("velocity_points", []))
    events = set(filter(None, str(total["notable_events"]).split(", ")))
    events.update(filter(None, str(current["notable_events"]).split(", ")))
    total["notable_events"] = ", ".join(sorted(events))


def write_park_plot(path: Path, rows: list[dict[str, object]]) -> None:
    """Write one dependency-free SVG chart per float/profile."""
    charts = []
    for row in rows:
        points = row.get("park_pressure_points", [])
        if not points:
            continue
        # Do not plot the terminal surface sample at approximately 0 dbar.
        if len(points) > 1 and points[-1][1] <= 2.0:
            points = points[:-1]
        if not points:
            continue
        width, height, left, right, top, bottom = 1100, 600, 80, 30, 45, 70
        times = [datetime.fromisoformat(point[0]).timestamp() for point in points]
        pressures = [point[1] for point in points]
        t_min, t_max = min(times), max(times)
        p_min, p_max = min(pressures), max(pressures)
        if t_max == t_min: t_max = t_min + 1
        if p_max == p_min: p_max = p_min + 1
        def x(value): return left + (value - t_min) / (t_max - t_min) * (width - left - right)
        def y(value): return top + (value - p_min) / (p_max - p_min) * (height - top - bottom)
        coords = " ".join(f"{x(datetime.fromisoformat(ts).timestamp())},{y(pressure)}" for ts, pressure in points)
        markers = "".join(f'<circle cx="{x(datetime.fromisoformat(ts).timestamp())}" cy="{y(pressure)}" r="4" fill="#2563eb"><title>{html.escape(ts)}: {pressure:.1f} dbar</title></circle>' for ts, pressure in points)
        tick_marks = []
        for index in range(5):
            tick_time = t_min + (t_max - t_min) * index / 4
            tick_x = x(tick_time)
            tick_label = datetime.fromtimestamp(tick_time, tz=timezone.utc).strftime("%m/%d %H:%M")
            tick_marks.append(f'<line x1="{tick_x}" y1="{top}" x2="{tick_x}" y2="{height-bottom}" stroke="#e5e7eb"/><text x="{tick_x}" y="{height-bottom+22}" text-anchor="middle">{tick_label}</text>')
        svg = f'''<svg viewBox="0 0 {width} {height}" role="img" aria-label="Park pressure for profile {html.escape(str(row["profile"]))}">
<rect width="{width}" height="{height}" fill="white"/>
{"".join(tick_marks)}
<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#374151"/>
<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#374151"/>
<polyline points="{coords}" fill="none" stroke="#2563eb" stroke-width="3"/>{markers}
<text x="{width/2}" y="{height-18}" text-anchor="middle">Date/time (UTC)</text>
<text x="18" y="{height/2}" transform="rotate(-90 18 {height/2})" text-anchor="middle">Pressure (dbar)</text>
<text x="{left-8}" y="{height-bottom+4}" text-anchor="end">{p_max:.1f}</text>
<text x="{left-8}" y="{top+4}" text-anchor="end">{p_min:.1f}</text>
</svg>'''
        charts.append(f'<h2>Float {html.escape(str(row["serial_number"]))} — Profile {html.escape(str(row["profile"]))}</h2><p>{len(points)} pressure readings</p>{svg}')
    body = "".join(charts) if charts else "<p>No park pressure readings were found.</p>"
    path.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>Park Pressure Plots</title><style>body{{font-family:Arial;margin:24px}}svg{{max-width:100%;border:1px solid #d1d5db;margin-bottom:36px}}</style></head><body><h1>Park Pressure vs. Time</h1>{body}</body></html>", encoding="utf-8")


def write_velocity_plot(path: Path, rows: list[dict[str, object]]) -> None:
    """Write one vertical-velocity SVG chart per float/profile."""
    charts = []
    for row in rows:
        points = row.get("velocity_points", [])
        if not points:
            continue
        width, height, left, right, top, bottom = 1100, 600, 80, 30, 45, 70
        pressures = [point[0] for point in points]
        velocities = [point[1] for point in points]
        p_min, p_max = min(pressures), max(pressures)
        v_min, v_max = min(velocities), max(velocities)
        if p_max == p_min: p_max = p_min + 1
        if v_max == v_min: v_max = v_min + 1
        def x(value): return left + (value - v_min) / (v_max - v_min) * (width - left - right)
        # Invert pressure/depth: low pressure at the top, high pressure at the bottom.
        def y(value): return top + (value - p_min) / (p_max - p_min) * (height - top - bottom)
        tick_marks = []
        for index in range(5):
            tick_velocity = v_min + (v_max - v_min) * index / 4
            tick_x = x(tick_velocity)
            tick_label = f"{tick_velocity:g}"
            tick_marks.append(f'<line x1="{tick_x}" y1="{top}" x2="{tick_x}" y2="{height-bottom}" stroke="#e5e7eb"/><text x="{tick_x}" y="{height-bottom+22}" text-anchor="middle">{tick_label}</text>')
        for index in range(5):
            tick_pressure = p_min + (p_max - p_min) * index / 4
            tick_y = y(tick_pressure)
            tick_label = f"{tick_pressure:g}"
            tick_marks.append(f'<line x1="{left}" y1="{tick_y}" x2="{width-right}" y2="{tick_y}" stroke="#e5e7eb"/><text x="{left-8}" y="{tick_y+4}" text-anchor="end">{tick_label}</text>')
        coords = " ".join(f"{x(value)},{y(pressure)}" for pressure, value in points)
        markers = "".join(f'<circle cx="{x(value)}" cy="{y(pressure)}" r="4" fill="#dc2626"><title>{pressure:g} dbar: {value:.3f} cm/s</title></circle>' for pressure, value in points)
        svg = f'''<svg viewBox="0 0 {width} {height}" role="img" aria-label="Vertical velocity for profile {html.escape(str(row["profile"]))}">
<rect width="{width}" height="{height}" fill="white"/>{"".join(tick_marks)}
<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#374151"/>
<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#374151"/>
<polyline points="{coords}" fill="none" stroke="#dc2626" stroke-width="3"/>{markers}
<text x="{width/2}" y="{height-18}" text-anchor="middle">Vertical velocity (cm/s)</text>
<text x="18" y="{height/2}" transform="rotate(-90 18 {height/2})" text-anchor="middle">Pressure (dbar)</text>
</svg>'''
        charts.append(f'<h2>Float {html.escape(str(row["serial_number"]))} — Profile {html.escape(str(row["profile"]))}</h2><p>{len(points)} velocity readings</p>{svg}')
    body = "".join(charts) if charts else "<p>No vertical velocity readings were found.</p>"
    path.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>Vertical Velocity Plots</title><style>body{{font-family:Arial;margin:24px}}svg{{max-width:100%;border:1px solid #d1d5db;margin-bottom:36px}}</style></head><body><h1>Vertical Velocity vs. Time</h1>{body}</body></html>", encoding="utf-8")


def write_overlay_plot(path: Path, rows: list[dict[str, object]], kind: str) -> None:
    """Write one overlay chart with a separate trace for each profile."""
    series = []
    for row in rows:
        key = "park_pressure_points" if kind == "park" else "velocity_points"
        points = row.get(key, [])
        if points:
            series.append((str(row["serial_number"]), str(row["profile"]), points))
    width, height, left, right, top, bottom = 1200, 700, 90, 35, 60, 80
    def trace_color(index: int) -> str:
        """Fade from light blue for early profiles to dark blue for later ones."""
        fraction = index / max(1, len(series) - 1)
        red = round(191 - 162 * fraction)
        green = round(219 - 144 * fraction)
        blue = round(254 - 34 * fraction)
        return f"rgb({red},{green},{blue})"
    legend = []
    if kind == "park":
        all_points = [point for _, _, points in series for point in points]
        x_values = [datetime.fromisoformat(point[0]).timestamp() for point in all_points]
        y_values = [point[1] for point in all_points]
        x_label, y_label = "Date/time (UTC)", "Pressure (dbar)"
    else:
        all_points = [point for _, _, points in series for point in points]
        x_values = [point[1] for point in all_points]
        y_values = [point[0] for point in all_points]
        x_label, y_label = "Vertical velocity (cm/s)", "Pressure (dbar)"
    if not all_points:
        body = "<p>No readings were found.</p>"
    else:
        x_min, x_max = min(x_values), max(x_values) or min(x_values) + 1
        y_min, y_max = min(y_values), max(y_values) or min(y_values) + 1
        if x_max == x_min: x_max = x_min + 1
        if y_max == y_min: y_max = y_min + 1
        def sx(value): return left + (value - x_min) / (x_max - x_min) * (width - left - right)
        def sy(value): return top + (value - y_min) / (y_max - y_min) * (height - top - bottom)
        parts = [f'<svg viewBox="0 0 {width} {height}" role="img"><rect width="{width}" height="{height}" fill="white"/>']
        for index in range(5):
            xv = x_min + (x_max - x_min) * index / 4
            yv = y_min + (y_max - y_min) * index / 4
            x_text = datetime.fromtimestamp(xv, tz=timezone.utc).strftime("%m/%d %H:%M") if kind == "park" else f"{xv:g}"
            parts.append(f'<line class="x-tick-line" data-index="{index}" x1="{sx(xv)}" y1="{top}" x2="{sx(xv)}" y2="{height-bottom}" stroke="#e5e7eb"/><text class="x-tick-label" data-index="{index}" x="{sx(xv)}" y="{height-bottom+24}" text-anchor="middle">{x_text}</text>')
            parts.append(f'<line x1="{left}" y1="{sy(yv)}" x2="{width-right}" y2="{sy(yv)}" stroke="#e5e7eb"/><text x="{left-8}" y="{sy(yv)+4}" text-anchor="end">{yv:g}</text>')
        for index, (serial, profile, points) in enumerate(series):
            color = trace_color(index)
            trace_id = f"{kind}_trace_{index}"
            coords = []
            for point_index, point in enumerate(points):
                xv = datetime.fromisoformat(point[0]).timestamp() if kind == "park" else point[1]
                yv = point[1] if kind == "park" else point[0]
                coords.append(f"{sx(xv)},{sy(yv)}")
            raw_points = []
            for point_index, point in enumerate(points):
                xv = datetime.fromisoformat(point[0]).timestamp() if kind == "park" else point[1]
                yv = point[1] if kind == "park" else point[0]
                raw_points.append([xv, yv])
            point_data = html.escape(json.dumps(raw_points), quote=True)
            parts.append(f'<polyline id="{trace_id}" data-points="{point_data}" points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="1.5"/>')
            markers = []
            if kind == "park":
                for point_index, point in enumerate(points):
                    xv = datetime.fromisoformat(point[0]).timestamp()
                    yv = point[1]
                    tooltip = f"{point[0]} | Pressure: {point[1]:g} dbar"
                    markers.append(f'<circle class="{trace_id}_marker" data-trace="{trace_id}" data-index="{point_index}" cx="{sx(xv)}" cy="{sy(yv)}" r="3" fill="{color}" stroke="white" stroke-width="1"><title>{html.escape(tooltip)}</title></circle>')
            else:
                # Invisible hit targets preserve hover details without drawing dots.
                for point_index, point in enumerate(points):
                    xv = point[1]
                    yv = point[0]
                    tooltip = f"Pressure: {point[0]:g} dbar | Vertical velocity: {point[1]:.3f} cm/s"
                    markers.append(f'<circle class="{trace_id}_marker" data-trace="{trace_id}" data-index="{point_index}" cx="{sx(xv)}" cy="{sy(yv)}" r="6" fill="transparent" stroke="none"><title>{html.escape(tooltip)}</title></circle>')
            parts.extend(markers)
            legend.append(f'<button class="legend-item active" onclick="toggleTrace(this, \'{trace_id}\')" ondblclick="isolateTrace(\'{trace_id}\')"><span class="swatch" style="background:{color}"></span>{html.escape(serial)} / Profile {html.escape(profile)}</button>')
        parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#374151"/><line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#374151"/><text x="{width/2}" y="{height-20}" text-anchor="middle">{x_label}</text><text x="18" y="{height/2}" transform="rotate(-90 18 {height/2})" text-anchor="middle">{y_label}</text></svg>')
        body = '<div class="legend">' + " ".join(legend) + '</div>' + "".join(parts)
    title = "Park Pressure Overlay" if kind == "park" else "Vertical Velocity Overlay"
    created = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    x_is_time = "true" if kind == "park" else "false"
    script = """<script>
const plotLeft=90, plotRight=35, plotWidth=1200, plotHeight=700, plotTop=60, plotBottom=80, xIsTime=""" + x_is_time + """;
function rescaleX(){
  const traces=[...document.querySelectorAll('polyline[id^=park_trace_],polyline[id^=velocity_trace_]')].filter(t=>t.style.display!=='none');
  const points=traces.flatMap(t=>JSON.parse(t.dataset.points));
  const allPoints=[...document.querySelectorAll('polyline[id^=park_trace_],polyline[id^=velocity_trace_]')].flatMap(t=>JSON.parse(t.dataset.points));
  if(!points.length)return;
  let xmin=Math.min(...points.map(p=>p[0])), xmax=Math.max(...points.map(p=>p[0]));
  if(xmin===xmax)xmax=xmin+1;
  document.querySelectorAll('.x-tick-line').forEach(line=>{const i=Number(line.dataset.index),v=xmin+(xmax-xmin)*i/4,px=plotLeft+(v-xmin)/(xmax-xmin)*(plotWidth-plotLeft-plotRight);line.setAttribute('x1',px);line.setAttribute('x2',px);});
  document.querySelectorAll('.x-tick-label').forEach(label=>{const i=Number(label.dataset.index),v=xmin+(xmax-xmin)*i/4,px=plotLeft+(v-xmin)/(xmax-xmin)*(plotWidth-plotLeft-plotRight);label.setAttribute('x',px);label.textContent=xIsTime?new Date(v*1000).toLocaleString([],{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):Number(v).toPrecision(4);});
  const ymin=Math.min(...allPoints.map(p=>p[1])), ymax=Math.max(...allPoints.map(p=>p[1]));
  traces.forEach(t=>{const data=JSON.parse(t.dataset.points);t.setAttribute('points',data.map(p=>`${plotLeft+(p[0]-xmin)/(xmax-xmin)*(plotWidth-plotLeft-plotRight)},${plotTop+(p[1]-ymin)/(ymax-ymin||1)*(plotHeight-plotTop-plotBottom)}`).join(' '));});
  document.querySelectorAll('circle[data-trace]').forEach(c=>{const trace=document.getElementById(c.dataset.trace);const data=JSON.parse(trace.dataset.points);const p=data[Number(c.dataset.index)];c.setAttribute('cx',plotLeft+(p[0]-xmin)/(xmax-xmin)*(plotWidth-plotLeft-plotRight));c.setAttribute('cy',plotTop+(p[1]-ymin)/(ymax-ymin||1)*(plotHeight-plotTop-plotBottom));});
}
function toggleTrace(button,id){const trace=document.getElementById(id);const visible=trace.style.display!=='none';trace.style.display=visible?'none':'inline';button.classList.toggle('active',!visible);rescaleX();}
function isolateTrace(id){document.querySelectorAll('.legend-item').forEach(button=>{const buttonId=button.getAttribute('ondblclick').match(/'([^']+)'/)[1];const active=buttonId===id;document.getElementById(buttonId).style.display=active?'inline':'none';button.classList.toggle('active',active);});rescaleX();}
</script>"""
    path.write_text(f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'><title>{title}</title><style>body{{background:#f8f9fa}}h1{{color:#123b5d}}.subtitle{{color:#6b7280;font-size:13px}}svg{{max-width:100%;width:100%;border:1px solid #d1d5db;background:white;border-radius:.375rem}}.legend{{display:flex;flex-wrap:wrap;gap:3px;margin:8px 0 12px}}.legend-item{{border:0;background:transparent;color:#374151;cursor:pointer;font:11px Arial;padding:2px 4px;opacity:.45}}.legend-item.active{{opacity:1}}.swatch{{display:inline-block;width:20px;height:2px;margin:0 4px 2px 0;vertical-align:middle}}</style></head><body><main class='container-fluid py-4'><div class='card shadow-sm'><div class='card-body'><h1 class='h3 mb-1'>{title}</h1><div class='subtitle mb-3'>Created {created}</div><div class='plot-wrap'>{body}</div></div></div></main>{script}</body></html>", encoding="utf-8")


def save_float_plots(rows: list[dict[str, object]]) -> None:
    """Save separate plot files in the folder matching each float serial."""
    rows_by_serial: dict[tuple[str, bool], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        rows_by_serial[(str(row["serial_number"]), bool(row.get("_is_partial")))].append(row)
    for (serial, partial), serial_rows in rows_by_serial.items():
        folder = ENGINEERING_ROOT / serial / ("partials" if partial else "")
        folder.mkdir(parents=True, exist_ok=True)
        write_overlay_plot(folder / "park_pressure_overlay.html", serial_rows, "park")
        write_overlay_plot(folder / "vertical_velocity_overlay.html", serial_rows, "velocity")
        write_latest_mission_json(folder / "mission.json")
        write_html(folder / "float_health_report.html", serial_rows)
        print(f"Saved plots to {folder}")
def write_html(path: Path, rows: list[dict[str, object]]) -> None:
    headers = "".join(f"<th>{html.escape(field)}</th>" for field in FIELDS)
    body = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(row[field]))}</td>" for field in FIELDS)
        body.append(f"<tr>{cells}</tr>")
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<title>Float Log Summary</title>
<style>
body {{ background: #f8f9fa; }}
.page-title {{ color: #123b5d; }}
.table-wrap {{ max-height: 78vh; overflow: auto; }}
table {{ min-width: 1800px; }}
thead th {{ position: sticky; top: 0; z-index: 2; white-space: nowrap; }}
tbody td {{ white-space: nowrap; vertical-align: middle; }}
</style>
</head>
<body>
<main class="container-fluid py-4">
<h1 class="page-title mb-1">Float Log Summary</h1>
<p class="text-secondary mb-3">Source folder: <code>{html.escape(str(LOG_PATH))}</code></p>
<a class="btn btn-primary btn-sm mb-3" href="mission.json">Mission</a>
<div class="card shadow-sm"><div class="card-body p-0"><div class="table-wrap">
<table class="table table-sm table-striped table-hover table-bordered align-middle mb-0">
<thead class="table-dark"><tr>{headers}</tr></thead>
<tbody>{''.join(body)}</tbody></table></div></div></div>
</main>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def main() -> None:
    if not LOG_PATH.is_dir():
        raise SystemExit(f"LOG_PATH is not a directory: {LOG_PATH}")

    if MISSION_ONLY:
        save_latest_mission()
        if SAVE_PLOTS_TO_FLOAT_FOLDER:
            serial_match = re.search(r"(\d+)$", LOG_PATH.name)
            if serial_match:
                engineering_folder = ENGINEERING_ROOT / serial_match.group(1)
                engineering_folder.mkdir(parents=True, exist_ok=True)
                write_latest_mission_json(engineering_folder / "mission.json")
        return

    summaries: dict[tuple[str, bool, str], dict[str, object]] = {}
    log_files = sorted(LOG_PATH.rglob("*.log"))
    if not log_files:
        raise SystemExit(f"No .log files found below: {LOG_PATH}")

    for path in log_files:
        serial = serial_from_filename(path)
        partial = is_partial_log(path)
        current = empty_summary(serial)
        parse_log(path, current)
        profile = str(current["profile"] or "Unknown")
        key = (serial, partial, profile)
        if key not in summaries:
            summaries[key] = empty_summary(serial)
            summaries[key]["profile"] = profile
            summaries[key]["_is_partial"] = partial
        merge_summary(summaries[key], current)

    rows = sorted(
        summaries.values(),
        key=lambda row: (
            str(row["serial_number"]),
            bool(row.get("_is_partial")),
            int(row["profile"]) if str(row["profile"]).isdigit() else 10**9,
            str(row["profile"]),
        ),
    )
    for summary in rows:
        finish_summary(summary)

    print("| " + " | ".join(FIELDS) + " |")
    print("| " + " | ".join("---" for _ in FIELDS) + " |")
    for row in rows:
        values = (str(row[field]).replace("|", "\\|") for field in FIELDS)
        print("| " + " | ".join(values) + " |")

    write_html(HTML_OUTPUT, rows)
    html_path = HTML_OUTPUT.resolve()
    print(f"\nRead {len(log_files)} log files. Wrote {html_path}")
    if OPEN_WINDOWS:
        webbrowser.open_new(html_path.as_uri())
    write_overlay_plot(PARK_OVERLAY_OUTPUT, rows, "park")
    write_overlay_plot(VELOCITY_OVERLAY_OUTPUT, rows, "velocity")
    if OPEN_WINDOWS:
        webbrowser.open_new(PARK_OVERLAY_OUTPUT.resolve().as_uri())
        webbrowser.open_new(VELOCITY_OVERLAY_OUTPUT.resolve().as_uri())
    if SAVE_PLOTS_TO_FLOAT_FOLDER:
        save_float_plots(rows)
    save_latest_mission()


if __name__ == "__main__":
    main()
