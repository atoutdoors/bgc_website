# Mission Paper Builder

This tool scans float `.msg` mission files, reconstructs mission-parameter changes between profiles, and builds an HTML paper with embedded figures.

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

By default, an existing paper in `Z:\www\bgc\engineering` is overwritten. To rebuild the analysis while preserving the existing server copy, use:

```bat
build_mission_paper_html.bat --no-overwrite
```

The explicit overwrite form is also available:

```bat
build_mission_paper_html.bat --overwrite
```

The data-folder argument and overwrite flag can be combined:

```bat
build_mission_paper_html.bat "D:\BGC\data" --no-overwrite
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

The input folder should contain float folders with `.msg` files below them. The builder searches all subfolders recursively.

Python 3.8 or newer is required. The launcher uses the local `navis\.venv` first, then `python` on `PATH`, and finally the Windows `py -3` launcher.

The labeled PNG plots use Plotly and Kaleido when those packages are installed. They include chart titles, axis labels, tick values, and bar-value annotations. If they are unavailable, the builder uses a basic unlabeled fallback and prints a warning; install the packages with `python -m pip install -r requirements.txt` for fully labeled plots.

## What it generates

Each run rescans the `.msg` files and regenerates the analysis files. The HTML paper is written to:

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

The builder groups message snapshots by float and profile, orders profiles numerically, and compares each profile with the preceding profile. Profile numbers are read from message filenames when available, then from `PrfId` or `Profile` headers.

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

`DeepProfileBuoyancyPos` and `ParkBuoyancyPos` changes are included only when the absolute difference is greater than 16 counts.

The report describes differences between available snapshots. It does not prove that a command was executed successfully or explain why a later telemetry event occurred.

## Progress and troubleshooting

The console shows file-counting, scan percentage, snapshot counts, float-comparison percentage, report-writing status, and the final output path. Python is run unbuffered so progress appears immediately.

Common errors:

- **No mission input data found:** confirm that `Z:\bgc\data` is available or pass the correct folder as the first BAT argument.
- **No parseable mission snapshots:** confirm the folder contains `.msg` files with a profile number in the filename or message contents.
- **Could not write requested output:** confirm that `Z:\www\bgc\engineering` is mounted and writable, or set `MISSION_PAPER_OUTPUT_DIR` to a writable folder.

## Updating the paper

Run the BAT file again whenever new messages arrive. The builder rescans all available `.msg` files on every run, replaces the CSVs and figures, and updates the `Last updated` timestamp in the HTML. By default it overwrites the report in the configured output folder; use `--no-overwrite` to preserve the existing server copy. It does not run continuously in the background.

