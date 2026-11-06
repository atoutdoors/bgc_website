# WHOI BGC Engineering Website

This project builds the WHOI BGC engineering website from engineering data retrieved from the WHOI float database. It creates the engineering summary table, float-specific plot pages, optional interactive plots, and one health report for each float.

## Main scripts

### `bgcwebsite.py`

The regular production script. It creates the engineering website outputs and includes float track maps and a combined GEBCO bathymetry plot when those switches are enabled.

### `bgcwebsite_test.py`

The test version. It uses the same engineering calculations and health-report logic, but map and bathymetry generation are disabled by default. Use it to test changes before running the regular script.

Both scripts are self-contained and use the same database/API workflow.

## Requirements

Install the required Python packages with:

```bash
pip install pandas plotly requests openpyxl kaleido
```

`kaleido` is only needed when PNG files are enabled. A web browser is needed for the interactive plot menu.

The script also needs access to the WHOI engineering database and the output locations configured in the script.

## Running the scripts

From the directory containing the script:

```bash
python bgcwebsite.py
```

or:

```bash
python bgcwebsite_test.py
```

The scripts print timestamped progress messages so the current stage can be identified during a long run.

## Configuration switches

The main switches are near the top of each script:

```python
WRITE_PNG = False
INTERACTIVE_PLOT_MENU = True
SAVE_PLOTS = False
HEALTH_REPORTS_ONLY = False
GENERATE_FLOAT_TRACK_MAPS = True
GENERATE_BATHYMETRY_MAPPING = True
GENERATE_PER_FLOAT_PLOTS = True
GENERATE_ALL_FLOAT_PLOTS = True
```

### Health reports only

To run the health-report portion without saving plots or opening the interactive plot menu:

```python
HEALTH_REPORTS_ONLY = True
```

This also disables map and bathymetry output. The script still downloads and prepares the engineering data needed by the reports.

### Interactive plot menu

The default interactive mode keeps figures in memory and opens a local browser menu after generation:

```python
INTERACTIVE_PLOT_MENU = True
SAVE_PLOTS = False
WRITE_PNG = False
```

Click a plot name to view that figure. Stop the local server with `Ctrl+C`.

### Save HTML plots

To write individual Plotly HTML files instead of using only the menu:

```python
INTERACTIVE_PLOT_MENU = False
SAVE_PLOTS = True
```

### Save PNG files

PNG output is optional and can take substantially longer than HTML generation:

```python
SAVE_PLOTS = True
WRITE_PNG = True
```

PNG files are queued and written in a batch near the end of the run.

### Plot categories

The category switches allow expensive sections to be disabled independently:

- `GENERATE_FLOAT_TRACK_MAPS` controls individual float track maps.
- `GENERATE_BATHYMETRY_MAPPING` controls the combined GEBCO bathymetry plot.
- `GENERATE_PER_FLOAT_PLOTS` controls plots inside each float directory.
- `GENERATE_ALL_FLOAT_PLOTS` controls plots comparing all floats.

## Output location

The output directory is selected by the `name` setting:

```python
name = 'Aidan'
```

The current branches point to the engineering website directory for the Aidan and Kat workstations. Add or update a branch if the script is being run from another workstation.

The script creates or updates:

```text
engineering/
├── engineeringtable.html
├── <serial number>/
│   ├── health_report.html
│   ├── index.html
│   └── <float plots>.html
├── by_parameter/
│   └── <across-float plots>.html
├── bathymetry.html                 # regular script when enabled
└── <serial number>/map.html        # regular script when enabled
```

The script also exports a dated engineering Excel file to the configured engineering-data export directory.

## Data workflow

The script runs as one end-to-end pipeline:

1. Download engineering records for all BGC floats from the WHOI database.
2. Export the downloaded engineering table to a dated Excel file.
3. Sort float serial numbers numerically and group records by `FloatId`.
4. Create the output directory for each float.
5. Calculate report dates, float ages, cycle intervals, and pressure statistics.
6. Retrieve maximum profile pressure data using concurrent API requests.
7. Generate per-float and across-float plots.
8. Generate one health report for each float.
9. Start the interactive plot menu or finish after writing the files, depending on the switches.

## Plot behavior

All plots use shared formatting from `style_figure()`. This provides consistent colors and legends, serial-number-based float colors, white hover labels with float serial numbers, plot creation dates in the title, and consistent fonts, margins, and backgrounds.

Cycle 0 is excluded from voltage, current, and amp plots because it is not treated as a normal operating cycle.

Extreme values can be filtered from plotted traces without changing the downloaded data or Excel export:

```python
FILTER_PLOT_OUTLIERS = True
OUTLIER_IQR_FACTOR = 9.0
```

Set `FILTER_PLOT_OUTLIERS = False` to display all plotted values.

## Health reports

Each float receives a self-contained file at:

```text
<serial number>/health_report.html
```

The report includes buoyancy pump runtime compared with the fleet average, quiescent voltage, latest humidity, humidity compared with that float's own average, latest time on the surface, park and deep-profile buoyancy positions, estimated connection failure rate, days since the latest report, and an overall health status.

Cycle 0 is excluded from health-report calculations.

### Health thresholds

| Metric | Good | Watch | Concern |
|---|---:|---:|---:|
| Days since latest report | 10 days or less | Over 10 days | Over 30 days |
| Buoyancy pump runtime vs fleet average | 130% or less | Over 130% | Over 155% |
| Quiescent voltage | 10 V or more | — | Below 10 V |
| Connection failure estimate | Below 20% | 20–50% | Over 50% |
| Humidity vs float average | Within 25% | 25–50% | Over 50% |

Runtime is calculated as:

```text
float recent average runtime / fleet average runtime * 100
```

Therefore, 100% means the float is at the fleet average, 130% means it is 30% above average, and 155% means it is 55% above average.

If either the latest humidity reading or the float's average humidity is below 1%, the humidity comparison is skipped and is not treated as a concern.

Park and deep-profile buoyancy metrics use the average of the last two readings divided by the absolute average for that same float, expressed as a percentage. They are not compared with the fleet average.

Insufficient data does not make a health report concerning. The report displays `Insufficient data` for that metric and does not add a concern score.

## Important functions

| Function | Purpose |
|---|---|
| `_get_dataframe()` | Sends a database request and converts the JSON response to a DataFrame. |
| `get_engineering_all()` | Retrieves engineering records for all floats. |
| `get_profile_stats_parallel()` | Retrieves profile statistics concurrently. |
| `serial_number_order()` | Sorts serial numbers numerically. |
| `filter_plot_outliers()` | Removes extreme plotted points without changing source data. |
| `style_figure()` | Applies shared Plotly colors, hover labels, titles, and layout. |
| `save_figure()` | Applies plot settings and registers or saves figures. |
| `serve_plot_menu()` | Opens the local interactive plot browser. |
| `health_status()` | Converts a metric and thresholds into Good, Watch, or Concern. |
| `last_readings_vs_own_average()` | Compares recent readings with a float's own average. |

## Troubleshooting

### The script seems stuck

The longest sections are usually API requests, plot construction across many floats, and PNG writing. Progress messages identify the current stage. PNG output can be disabled with:

```python
WRITE_PNG = False
```

For a faster health check, use:

```python
HEALTH_REPORTS_ONLY = True
```

### Timezone subtraction error

Telemetry dates are converted with `pd.to_datetime(..., utc=True)` before calculating report age. This prevents subtraction between timezone-aware and timezone-naive timestamps.

### Missing output files

Check the `name` setting and the corresponding `filedir` branch. Also confirm that the output directory is writable and that the relevant generation switch is enabled.

### Missing PNG files

Confirm the following settings:

```python
SAVE_PLOTS = True
WRITE_PNG = True
```

Also install `kaleido` if Plotly reports that no image renderer is available.

### GEBCO plot problems

The regular script requests a cached GEBCO WMS image from the GEBCO service. Disable the bathymetry section if the network is unavailable:

```python
GENERATE_BATHYMETRY_MAPPING = False
```
