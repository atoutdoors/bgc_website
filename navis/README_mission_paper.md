# Mission Paper Builder

This tool uses each float's full profile-0 `.msg` mission as a baseline, then reconstructs mission-parameter changes from accepted `.log` configuration blocks and builds an HTML paper with embedded figures.

## Quick start

### Option 1: File Explorer

1. Make sure the server folders `Z:\bgc\data` and `Z:\www\bgc\engineering` are available.
2. Open the `navis` folder.
3. Double-click:

```text
build_mission_paper_html.bat
```

4. Watch the console. It reports the number of files found, scan percentage, comparison percentage, and output path.
5. Press a key if the window remains open after an error.

Open the completed report at:

```text
Z:\www\bgc\engineering\navis_mission_changes_paper.html
```

### Option 2: Command Prompt

1. Open Command Prompt.
2. Change to the folder containing the BAT file:

```bat
cd /d C:\path\to\bgc_website\navis
```

3. Run the builder:

```bat
build_mission_paper_html.bat
```

To use a different mission-data folder, pass it as the first argument:

```bat
build_mission_paper_html.bat "C:\path\to\mission\data"
```

Set `OVERWRITE_EXISTING_PAPER` near the top of `build_mission_paper_html.py` to control whether an existing paper in `Z:\www\bgc\engineering` is replaced:

```python
OVERWRITE_EXISTING_PAPER = False  # preserve the existing server copy
```

Set it to `True` when the server copy should be replaced:

```python
OVERWRITE_EXISTING_PAPER = True
```

The data-folder argument remains available:

```bat
build_mission_paper_html.bat "D:\BGC\data"
```

For example:

```bat
build_mission_paper_html.bat "D:\BGC\data"
```

### Option 3: PowerShell

1. Open PowerShell.
2. Change to the `navis` folder:

```powershell
Set-Location "C:\path\to\bgc_website\navis"
```

3. Run the BAT file:

```powershell
& .\build_mission_paper_html.bat
```

With a custom input folder:

```powershell
& .\build_mission_paper_html.bat "D:\BGC\data"
```

Do not close the console while it is scanning. Large server folders can take several minutes; the percentage messages confirm that the scan is still active.

The default input folder is:

```text
Z:\bgc\data
```

The input folder should contain float folders with `.log` files below them. The builder searches all subfolders recursively.

All parameters require logfile evidence between `Parsing configurators in "mission.cfg".` and `Configuration accepted.` containing the parameter and new value. No mission parameters are manually excluded.

Python 3.8 or newer is required. The launcher uses the local `navis\.venv` first, then `python` on `PATH`, and finally the Windows `py -3` launcher.

The PNG plots use Plotly and Kaleido when those packages are installed. They include chart titles, axis labels, tick values, and bar-value annotations. If image export is unavailable, the builder prints a warning and uses a dependency-free fallback that still includes the chart title and x/y axis labels.

## What it generates

Each run rescans the `.log` files and regenerates the analysis files. The HTML paper is written to:

```text
Z:\www\bgc\engineering\navis_mission_changes_paper.html
```

A local copy and the intermediate files are kept under:

```text
navis\analysis_output\mission_analysis\
```

This folder contains:

- `mission_float_summary_filtered.csv` — profile and change counts by float
- `mission_change_events_filtered.csv` — old and new values for each detected change
- `figures_filtered\` — PNG figures embedded in the paper
- `navis_mission_changes_paper.html` — local backup of the report

## Output location override

To write the paper somewhere other than the default network folder, set `MISSION_PAPER_OUTPUT_DIR` before running:

```bat
set MISSION_PAPER_OUTPUT_DIR=C:\reports
build_mission_paper_html.bat
```

The output folder is created if it does not already exist.

For a one-time PowerShell run:

```powershell
$env:MISSION_PAPER_OUTPUT_DIR = 'C:\reports'
& .\build_mission_paper_html.bat
```

For a one-time Command Prompt run:

```bat
set "MISSION_PAPER_OUTPUT_DIR=C:\reports"
build_mission_paper_html.bat
```

## How changes are detected

The builder uses the full profile-0 `.msg` mission as the initial state, then groups accepted `mission.cfg` blocks by float, orders them chronologically, carries forward omitted parameters, and compares each block with the preceding state. This captures parameters that are absent from later `.msg` files.

The report is intentionally limited to the mission configurators defined in the Navis Float Mission Control Manual:

- `ActivateRecoveryMode`
- `AirBladderMax`
- `AscentTimeOut`
- `AtDialCmd`
- `AltDialCmd`
- `BuoyancyNudge`
- `ConnectTimeOut`
- `CpActivationP`
- `DeepProfileDescentTime`
- `DeepProfileBuoyancyPos`
- `DeepProfilePressure`
- `DownTime`
- `FlashErase`
- `FlashCreate`
- `FloatId`
- `IsusInit`
- `MaxLogKb`
- `ParkDescentTime`
- `ParkBuoyancyPos`
- `ParkPressure`
- `PnPCycleLen`
- `Pwd`
- `TelemetryRetry`
- `TimeOfDay`
- `UpTime`
- `User`
- `Verbosity`

Other telemetry and engineering fields are ignored.

The report describes differences between available snapshots. It does not prove that a command was executed successfully or explain why a later telemetry event occurred.

Only parameter values found between `Parsing configurators in "mission.cfg".` and `Configuration accepted.` are compared. Parameters outside accepted configuration blocks are ignored.

## Progress and troubleshooting

The console shows file-counting, scan percentage, snapshot counts, float-comparison percentage, report-writing status, and the final output path. Python is run unbuffered so progress appears immediately.

Common errors:

- **No mission input data found:** confirm that `Z:\bgc\data` is available or pass the correct folder as the first BAT argument.
- **No accepted mission configuration blocks:** confirm the folder contains `.log` files with `Parsing configurators in "mission.cfg".` followed by `Configuration accepted.`.
- **Could not write requested output:** confirm that `Z:\www\bgc\engineering` is mounted and writable, or set `MISSION_PAPER_OUTPUT_DIR` to a writable folder.

## Updating the paper

Run the BAT file again whenever new logs arrive. The builder rescans all available `.log` files on every run, replaces the CSVs and figures, and updates the `Last updated` timestamp in the HTML. The `OVERWRITE_EXISTING_PAPER` setting controls whether it replaces the report in the configured output folder. It does not run continuously in the background.

