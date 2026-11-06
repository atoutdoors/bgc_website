# BGC Engineering Website Scripts

These scripts download WHOI BGC float engineering data and create the engineering website outputs, plots, tables, and per-float health reports.

## Scripts

### `bgcwebsite.py`

The regular production script. It generates the engineering website plots, engineering table, optional maps and GEBCO bathymetry, and per-float health reports.

### `bgcwebsite_test.py`

The testing version. It uses the same data processing and health-report logic, but maps and bathymetry are disabled by default. It also supports plot-only testing and the sequential Turbo trace colors.

### `bgcwebsite_test_layouts.py`

An alternate test branch that runs `bgcwebsite_test.py` with:

- Small-multiples layouts for across-float plots
- One subplot per named trace
- Shared x-axes
- Turbo sequential trace colors
- Plot-only mode, with health reports skipped

Run it with:

```bash
python bgcwebsite_test_layouts.py
```

## Installation

The required packages are:

```bash
pip install pandas plotly requests openpyxl kaleido
```

The provided `setup_bgc_environment.bat` file creates or updates a `.venv` in the directory where it is run. It installs the packages and verifies Plotly's Turbo colormap.

Run the setup file from the desired project directory:

```text
setup_bgc_environment.bat
```

Then run a script with:

```bat
.venv\Scripts\python.exe bgcwebsite.py
```

## Basic configuration

The main switches are near the top of the scripts:

```python
WRITE_PNG = False
INTERACTIVE_PLOT_MENU = True
SAVE_PLOTS = False
HEALTH_REPORTS_ONLY = False
PLOTS_ONLY = False
```

The regular script also includes:

```python
GENERATE_FLOAT_TRACK_MAPS = True
GENERATE_BATHYMETRY_MAPPING = True
GENERATE_PER_FLOAT_PLOTS = True
GENERATE_ALL_FLOAT_PLOTS = True
```

The test script has maps and bathymetry disabled by default.

## Run modes

### Normal production run

```python
HEALTH_REPORTS_ONLY = False
PLOTS_ONLY = False
```

This runs the engineering data workflow, plot generation, and health reports.

### Health reports only

```python
HEALTH_REPORTS_ONLY = True
```

This suppresses plot output, maps, bathymetry, PNG generation, and the interactive plot menu while still preparing the engineering data needed for health reports.

### Plot-only testing

In `bgcwebsite_test.py`:

```python
PLOTS_ONLY = True
```

This runs the plot workflow and stops before health-report generation. It is useful for testing layout, hover labels, and trace colors.

For saved plots:

```python
PLOTS_ONLY = True
SAVE_PLOTS = True
INTERACTIVE_PLOT_MENU = False
```

`HEALTH_REPORTS_ONLY` and `PLOTS_ONLY` cannot both be enabled.

### Interactive plot menu

```python
INTERACTIVE_PLOT_MENU = True
SAVE_PLOTS = False
WRITE_PNG = False
```

After generation, the script opens a local browser menu. Select a plot name to render that figure. Stop the local server with `Ctrl+C`.

### Saved HTML and PNG plots

```python
INTERACTIVE_PLOT_MENU = False
SAVE_PLOTS = True
WRITE_PNG = True
```

PNG files are queued and written together near the end of the run. PNG generation is usually the slowest output step.

## Plot colors and layouts

Multi-trace plots use Plotly's sequential `Turbo` colormap. Colors are assigned in trace order, so the first and last traces receive different colors across the palette. Single-trace plots retain their normal float or legend colors.

The standard scripts use overlaid traces for direct comparison. The layout branch uses small multiples for across-float plots:

```text
Float 1 trace
Float 2 trace
Float 3 trace
...
```

Small multiples are useful when overlaid traces become difficult to distinguish.

Cycle 0 is excluded from voltage, amp, and current plots and from health-report calculations.

## Data workflow

The scripts run as one pipeline:

1. Download engineering records from the WHOI float database.
2. Export the downloaded records to a dated Excel file.
3. Sort serial numbers numerically and group records by float.
4. Create output folders for each float.
5. Calculate report dates, float age, cycle intervals, and pressure statistics.
6. Retrieve maximum profile pressures using concurrent API requests.
7. Generate per-float and across-float plots.
8. Generate health reports unless plot-only mode is enabled.
9. Open the interactive plot menu or finish after saving files.

## Output structure

The output directory is controlled by the `name` setting and `filedir` branches near the middle of the script.

Typical output:

```text
engineering/
├── engineeringtable.html
├── <serial number>/
│   ├── health_report.html
│   ├── <individual plots>.html
│   └── <individual plots>.png
├── by_parameter/
│   ├── <across-float plots>.html
│   └── <across-float plots>.png
├── <serial number>/map.html
└── bathymetry.html
```

The map and bathymetry files are generated only when their switches are enabled.

## Health reports

Each float receives:

```text
<serial number>/health_report.html
```

The report contains:

- Buoyancy pump runtime versus fleet average
- Quiescent voltage
- Latest humidity
- Humidity versus that float's own average
- Latest time on surface
- Park buoyancy position versus that float's own average
- Deep-profile buoyancy position versus that float's own average
- Connection failure estimate
- Days since latest report
- Overall status

### Current thresholds

| Metric | Watch | Concern |
|---|---:|---:|
| Days since latest report | Over 10 days | Over 30 days |
| Pump runtime vs fleet average | Over 130% | Over 155% |
| Quiescent voltage | — | Below 10 V |
| Connection failure estimate | 20–50% | Over 50% |
| Humidity difference | 25–50% | Over 50% |

Pump runtime is calculated as:

```text
float recent average runtime / fleet average runtime * 100
```

Therefore, 100% equals the fleet average, 130% is 30% above average, and 155% is 55% above average.

If either the latest humidity or the float's average humidity is below 1%, the humidity comparison is skipped. Insufficient data does not make a report concerning.

## Performance notes

The longest stages are usually:

- Database/API requests
- Maximum-pressure requests
- Construction of many Plotly figures
- PNG writing

For faster visual testing, use `PLOTS_ONLY = True` and keep `WRITE_PNG = False` until the plots look correct.

## Troubleshooting

### `No module named pandas`

Use the same interpreter for installation and execution:

```bat
.venv\Scripts\python.exe -m pip install pandas
.venv\Scripts\python.exe bgcwebsite_test.py
```

### Timezone subtraction error

Telemetry timestamps are converted to UTC before report-age calculations so timezone-aware and timezone-naive values are not subtracted directly.

### Missing plot files

Confirm:

```python
SAVE_PLOTS = True
```

For PNG files, also set:

```python
WRITE_PNG = True
```

### Missing GEBCO or map files

Enable the relevant switches in `bgcwebsite.py`:

```python
GENERATE_FLOAT_TRACK_MAPS = True
GENERATE_BATHYMETRY_MAPPING = True
```
