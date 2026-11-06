# S2BGC Engineering Reports

These scripts generate HTML engineering reports and Plotly visualizations from S2BGC L0 JSON files.

## Expected data layout

The scripts expect float data in this structure:

```text
Z:\S2BGC\data\<serial>\json\L0\*.json
```

The generated website files are written to:

```text
Z:\www\bgc\engineering\S2BGC\
```

## Configuration

Edit `run_engineering_for_serials.py` and set the serial numbers to process:

```python
SERIAL_NUMBERS = ["4056", "4057"]
```

The script generates:

- `engineeringtable.html` — summary table for all configured floats.
- `humidity.html` — combined relative-humidity plot.
- `all_floats_engineering_profiles.html` — one chart per engineering parameter with one trace per float.
- `<serial>\index.html` — Bootstrap-styled page for each float.
- `<serial>\<serial>_humidity.html` — relative humidity versus profile.
- `<serial>\<serial>_engineering_profiles.html` — engineering parameters versus profile.

## Running

From the `S2BGC` folder:

```powershell
py run_engineering_for_serials.py
```

The batch runner calls `extract_engineering_data.py` for each configured serial number and then creates the combined reports and engineering table.

## Virtual environment

Run `setup_s2bgc_venv.bat` to create or activate a local `.venv` and run the report generator.

The HTML pages load Plotly, Bootstrap, and DataTables from CDNs, so a browser needs internet access to display the styling and interactive charts.
