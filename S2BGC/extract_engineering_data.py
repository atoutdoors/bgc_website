#!/usr/bin/env python3
"""Extract engineering data from all S2BGC L0 JSON files for a float.

The script creates an HTML table for:
  1. The decoded Engineering_Data key/value records.
  2. Pump events.
  3. Packet types whose description contains "Engineering".

Examples:
    python extract_engineering_data.py
    python extract_engineering_data.py 4056
    python extract_engineering_data.py 4056 --no-open
    python extract_engineering_data.py 4056 --root Z:\\S2BGC\\data
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any
import webbrowser

# Set the float serial number here when running the script without arguments.
SERIAL_NUMBER = "4056"
# Set to False to save the combined report without opening a browser window.
OPEN_HTML_WINDOW = True
# Set to True to save a separate <serial>_humidity.html Plotly report.
SAVE_HUMIDITY_PLOT = True
# Set to True to save one profile plot for every numeric Engineering_Data field.
SAVE_PROFILE_PLOTS = True
# Folder for the separate humidity Plotly reports.
HUMIDITY_PLOT_DIR = Path(r"Z:\www\bgc\engineering\S2BGC")


def parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def markdown_cell(value: Any) -> str:
    """Convert a value to a safe, compact Markdown-table cell."""
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = str(value).lower()
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def make_table(headers: list[str], rows: list[list[Any]]) -> str:
    """Build a GitHub-flavored Markdown table."""
    header = "| " + " | ".join(markdown_cell(item) for item in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(markdown_cell(item) for item in row) + " |"
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def relative_humidity_plot_html(records: list[tuple[Path, dict[str, Any]]]) -> str:
    """Create a Plotly humidity-versus-profile chart for the loaded files."""
    points = []
    for source, data in records:
        rh_record = data.get("Engineering_Data", {}).get("RH")
        if not isinstance(rh_record, dict):
            continue
        if rh_record.get("value") is None or data.get("CYCLE_NUMBER") is None:
            continue
        points.append(
            {
                "profile": data.get("CYCLE_NUMBER"),
                "humidity": rh_record.get("value"),
                "file": source.name,
            }
        )

    points_json = json.dumps(points)
    return f"""
<h2>Relative Humidity vs Profile</h2>
<div id="relative-humidity-plot" style="width:100%;height:520px;"></div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>
const humidityPoints = {points_json};
const humidityTrace = {{
  x: humidityPoints.map(point => point.profile),
  y: humidityPoints.map(point => point.humidity),
  text: humidityPoints.map(point => point.file),
  mode: 'lines+markers',
  type: 'scatter',
  marker: {{size: 8}},
  hovertemplate: 'Profile: %{{x}}<br>Relative humidity: %{{y}}%<br>%{{text}}<extra></extra>'
}};
Plotly.newPlot('relative-humidity-plot', [humidityTrace], {{
  title: 'Relative Humidity vs Profile',
  xaxis: {{title: 'Profile / cycle number', dtick: 1}},
  yaxis: {{title: 'Relative humidity (%)'}},
  hovermode: 'closest',
  margin: {{t: 60, r: 30, b: 70, l: 70}}
}}, {{responsive: true}});
</script>
"""


def standalone_humidity_html(
    records: list[tuple[Path, dict[str, Any]]], serial: str
) -> str:
    """Create a standalone HTML document containing only the RH plot."""
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>{serial} Relative Humidity</title>
<style>body {{ font-family: Arial, sans-serif; margin: 24px; }}</style>
</head><body>
{relative_humidity_plot_html(records)}
</body></html>"""


def engineering_profile_plots_html(
    records: list[tuple[Path, dict[str, Any]]], serial: str
) -> str:
    """Create one Plotly chart per numeric Engineering_Data parameter."""
    parameters: dict[str, list[dict[str, Any]]] = {}
    for source, data in records:
        cycle = data.get("CYCLE_NUMBER")
        engineering = data.get("Engineering_Data", {})
        if cycle is None or not isinstance(engineering, dict):
            continue
        for name, record in engineering.items():
            if not isinstance(record, dict):
                continue
            value = record.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            parameters.setdefault(name, []).append(
                {"profile": cycle, "value": value, "file": source.name}
            )

    chart_data = []
    for name, points in sorted(parameters.items()):
        points.sort(key=lambda point: (point["profile"], point["file"]))
        unit = next(
            (
                record.get("unit", "")
                for _, data in records
                for parameter, record in data.get("Engineering_Data", {}).items()
                if parameter == name and isinstance(record, dict)
            ),
        )
        chart_data.append({"name": name, "unit": unit, "points": points})

    chart_data_json = json.dumps(chart_data)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>S2BGC Float {serial} Engineering Profiles</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body {{ background:#f6f8fa; }} .plot-card {{ background:white; margin-bottom:24px; }}</style>
</head><body><main class="container py-4">
<h1 class="h3 mb-4">Float {serial} Engineering Data Across Profiles</h1>
<div id="plots"></div>
<script>
const chartData = {chart_data_json};
const plots = document.getElementById('plots');
chartData.forEach((chart, index) => {{
  const card = document.createElement('div');
  card.className = 'card shadow-sm plot-card';
  const plot = document.createElement('div');
  plot.id = 'plot-' + index;
  plot.style.height = '420px';
  card.appendChild(plot);
  plots.appendChild(card);
  Plotly.newPlot(plot, [{{
    x: chart.points.map(point => point.profile),
    y: chart.points.map(point => point.value),
    text: chart.points.map(point => point.file),
    mode: 'lines+markers',
    type: 'scatter',
    marker: {{size: 7}},
    hovertemplate: 'Profile: %{{x}}<br>Value: %{{y}}<br>%{{text}}<extra></extra>'
  }}], {{
    title: chart.name,
    xaxis: {{title: 'Profile / cycle number', dtick: 1}},
    yaxis: {{title: chart.unit ? chart.name + ' (' + chart.unit + ')' : chart.name}},
    margin: {{t: 60, r: 25, b: 65, l: 80}}
  }}, {{responsive: true}});
}});
</script></main></body></html>"""


def vertical_velocity_plot_html(
    records: list[tuple[Path, dict[str, Any]]]
) -> str:
    """Create a Plotly pressure-rate plot from Fall and Rise records."""
    points: list[dict[str, Any]] = []
    for source, data in records:
        profile_events = []
        for section in ("Fall", "Rise"):
            for event in data.get(section, []) or []:
                if isinstance(event, dict):
                    timestamp = parse_time(event.get("TIME"))
                    pressure = event.get("PRES")
                    if timestamp is not None and isinstance(pressure, (int, float)):
                        profile_events.append((timestamp, float(pressure)))
        profile_events.sort(key=lambda item: item[0])
        for previous, current in zip(profile_events, profile_events[1:]):
            seconds = (current[0] - previous[0]).total_seconds()
            if seconds <= 0:
                continue
            points.append(
                {
                    "time": current[0].isoformat(),
                    "velocity": (current[1] - previous[1]) / seconds,
                    "file": source.name,
                }
            )

    points_json = json.dumps(points)
    return f"""
<h2>Vertical Velocity</h2>
<div id="vertical-velocity-plot" style="width:100%;height:520px;"></div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>
const velocityPoints = {points_json};
const velocityTrace = {{
  x: velocityPoints.map(point => point.time),
  y: velocityPoints.map(point => point.velocity),
  text: velocityPoints.map(point => point.file),
  mode: 'lines+markers',
  type: 'scatter',
  marker: {{size: 5}},
  hovertemplate: 'Time: %{{x}}<br>Vertical velocity: %{{y:.4f}} dbar/s<br>%{{text}}<extra></extra>'
}};
Plotly.newPlot('vertical-velocity-plot', [velocityTrace], {{
  title: 'Vertical Velocity',
  xaxis: {{title: 'Time', type: 'date'}},
  yaxis: {{title: 'Vertical velocity (dbar/s)'}},
  hovermode: 'closest',
  margin: {{t: 60, r: 30, b: 70, l: 80}}
}}, {{responsive: true}});
</script>
"""


def standalone_vertical_velocity_html(
    records: list[tuple[Path, dict[str, Any]]], serial: str
) -> str:
    """Create a standalone HTML document containing only the velocity plot."""
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>{serial} Vertical Velocity</title>
<style>body {{ font-family: Arial, sans-serif; margin: 24px; }}</style>
</head><body>
{vertical_velocity_plot_html(records)}
</body></html>"""


def markdown_to_html(
    markdown: str, records: list[tuple[Path, dict[str, Any]]]
) -> str:
    """Convert the limited Markdown produced by this script into standalone HTML."""
    output: list[str] = []
    in_table = False
    for line in markdown.splitlines():
        if line.startswith("# "):
            output.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_table:
                output.append("</table>")
                in_table = False
            output.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("| "):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if all(set(cell) <= {"-"} for cell in cells):
                continue
            if not in_table:
                output.append("<table><thead><tr>")
                output.extend(f"<th>{html.escape(cell)}</th>" for cell in cells)
                output.append("</tr></thead><tbody>")
                in_table = True
            else:
                output.append("<tr>")
                output.extend(f"<td>{html.escape(cell)}</td>" for cell in cells)
                output.append("</tr>")
        elif line.strip() == "":
            if in_table:
                output.append("</tbody></table>")
                in_table = False
        else:
            output.append(f"<p>{html.escape(line)}</p>")
    if in_table:
        output.append("</tbody></table>")
    return """<!doctype html>
<html><head><meta charset="utf-8"><title>S2BGC Engineering Data</title>
<style>
body { font-family: Arial, sans-serif; margin: 24px; color: #222; }
h1 { color: #123b5d; } h2 { margin-top: 28px; color: #245a7a; }
table { border-collapse: collapse; margin: 10px 0 24px; width: 100%; }
th, td { border: 1px solid #bbb; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #eaf2f8; position: sticky; top: 0; }
tr:nth-child(even) { background: #f8fbfd; }
</style></head><body>
""" + relative_humidity_plot_html(records) + "\n".join(output) + "</body></html>"


def extract_engineering_data(records: list[tuple[Path, dict[str, Any]]], serial: str) -> str:
    metadata_rows: list[list[Any]] = []
    engineering_rows: list[list[Any]] = []
    pump_rows: list[list[Any]] = []
    packet_rows: list[list[Any]] = []

    for source, data in records:
        metadata_rows.append(
            [
                source.name,
                data.get("FILE_CREATION_DATE"),
                data.get("INTERNAL_ID_NUMBER"),
                data.get("DAC_ID_NUMBER"),
                data.get("WMO_ID_NUMBER"),
                data.get("CYCLE_NUMBER"),
            ]
        )

        for name, record in data.get("Engineering_Data", {}).items():
            if isinstance(record, dict):
                engineering_rows.append(
                    [
                        source.name,
                        name,
                        record.get("value"),
                        record.get("unit"),
                        record.get("description"),
                    ]
                )

        for event in data.get("Pump", []):
            pump_rows.append(
                [
                    source.name,
                    event.get("TIME"),
                    event.get("PRES"),
                    event.get("current"),
                    event.get("voltage"),
                    event.get("pump_time"),
                    event.get("vac_start"),
                    event.get("vac_end"),
                    event.get("phase"),
                    event.get("description"),
                ]
            )

        for packet in data.get("packet_info", {}).get("packet_type", []):
            if "engineering" in str(packet.get("description", "")).lower():
                packet_rows.append(
                    [
                        source.name,
                        packet.get("id"),
                        packet.get("bytes"),
                        packet.get("packets"),
                        packet.get("description"),
                    ]
                )

    lines = [
        f"# Engineering Data: Float `{serial}`",
        "",
        f"Files read: **{len(records)}**",
        "",
        make_table(
            ["Source file", "File creation date", "Internal ID", "DAC ID", "WMO ID", "Cycle"],
            metadata_rows,
        ),
        "",
        "## Decoded Engineering_Data",
        "",
        make_table(
            ["Source file", "Parameter", "Value", "Unit", "Description"],
            engineering_rows,
        ),
        "",
        "## Pump events",
        "",
        make_table(
            [
                "Source file",
                "Time",
                "Pressure (dbar)",
                "Current (mA)",
                "Voltage (V)",
                "Pump time (s)",
                "Vacuum start",
                "Vacuum end",
                "Phase",
                "Description",
            ],
            pump_rows,
        ),
        "",
        "## Engineering packet summary",
        "",
        make_table(
            ["Source file", "Packet ID", "Bytes", "Packets", "Description"],
            packet_rows,
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract engineering and pump data from all S2BGC L0 JSON files for a float."
    )
    parser.add_argument(
        "serial",
        nargs="?",
        default=SERIAL_NUMBER,
        help="Four-digit float serial number; defaults to SERIAL_NUMBER above",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(r"Z:\S2BGC\data"),
        help=r"Data root containing <serial>\json\L0 (default: Z:\S2BGC\data)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output HTML file; defaults to engineering_<serial>.html",
    )
    parser.add_argument(
        "--open-window",
        dest="open_window",
        action="store_true",
        help="Open the combined HTML report in the default browser",
    )
    parser.add_argument(
        "--no-open",
        dest="open_window",
        action="store_false",
        help="Save the HTML report without opening a browser window",
    )
    parser.add_argument(
        "--save-humidity-plot",
        dest="save_humidity_plot",
        action="store_true",
        help="Save a separate <serial>_humidity.html Plotly file",
    )
    parser.add_argument(
        "--no-save-humidity-plot",
        dest="save_humidity_plot",
        action="store_false",
        help="Do not save the separate humidity Plotly file",
    )
    parser.set_defaults(
        open_window=OPEN_HTML_WINDOW,
        save_humidity_plot=SAVE_HUMIDITY_PLOT,
    )
    args = parser.parse_args()

    serial = str(args.serial).zfill(4)
    input_dir = args.root / serial / "json" / "L0"
    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        raise SystemExit(f"No JSON files found in {input_dir}")

    records: list[tuple[Path, dict[str, Any]]] = []
    for json_file in json_files:
        with json_file.open("r", encoding="utf-8") as handle:
            records.append((json_file, json.load(handle)))

    markdown = extract_engineering_data(records, serial)
    output_path = args.output or Path.cwd() / f"engineering_{serial}.html"
    output_path.write_text(
        markdown_to_html(markdown, records), encoding="utf-8"
    )
    if args.save_humidity_plot:
        float_plot_dir = HUMIDITY_PLOT_DIR / serial
        float_plot_dir.mkdir(parents=True, exist_ok=True)
        humidity_path = float_plot_dir / f"{serial}_humidity.html"
        humidity_path.write_text(
            standalone_humidity_html(records, serial), encoding="utf-8"
        )
        print(f"Saved humidity plot to {humidity_path.resolve()}")
    if SAVE_PROFILE_PLOTS:
        float_plot_dir = HUMIDITY_PLOT_DIR / serial
        float_plot_dir.mkdir(parents=True, exist_ok=True)
        profile_path = float_plot_dir / f"{serial}_engineering_profiles.html"
        profile_path.write_text(
            engineering_profile_plots_html(records, serial), encoding="utf-8"
        )
        print(f"Saved engineering profile plots to {profile_path.resolve()}")
    if args.open_window:
        webbrowser.open_new_tab(output_path.resolve().as_uri())
    print(f"Saved HTML table to {output_path.resolve()}")


if __name__ == "__main__":
    main()
