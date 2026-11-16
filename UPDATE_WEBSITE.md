# Complete Website Update Instructions

## 1. Prepare the workstation

Open Command Prompt or PowerShell and run:

```bat
cd /d C:\Users\athay\Documents\bgc_website
git status
git pull origin main
```

Resolve any existing changes or pull conflicts before continuing. Confirm that the `Z:` drive is connected:

```bat
dir Z:\bgc\data
dir Z:\bgc\data\www\bgc\engineering
```

The source data is in `Z:\bgc\data`; generated engineering files belong in `Z:\bgc\data\www\bgc\engineering`.

## 2. Set up Python

For the website scripts, run the setup file once on a new or repaired workstation:

```bat
cd /d C:\Users\athay\Documents\bgc_website\navis
setup_bgc_environment.bat
```

For the float-log parser, use its separate setup file:

```bat
cd /d C:\Users\athay\Documents\bgc_website\navis_logfile_parsing
setup_float_parser_venv.bat
```

These scripts create or repair a local `.venv` and install the required packages.

## 3. Make and test changes

The production script is `navis\bgcwebsite.py`. The test script is `navis\bgcwebsite_test.py`. Use the test script first:

```bat
cd /d C:\Users\athay\Documents\bgc_website\navis
.venv\Scripts\python.exe bgcwebsite_test.py
```

Common settings near the top of the scripts are:

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

For faster testing, use `HEALTH_REPORTS_ONLY = True` or `PLOTS_ONLY = True`. Keep `WRITE_PNG = False` until the HTML plots are correct. Do not edit generated HTML or Excel files by hand; regenerate them from the scripts.

## 4. Run the complete production update

After the test succeeds, run:

```bat
cd /d C:\Users\athay\Documents\bgc_website\navis
.venv\Scripts\python.exe bgcwebsite.py
```

This retrieves current engineering records, exports the dated Excel data, and generates the configured engineering table, float pages, plots, health reports, maps, and bathymetry.

If the interactive plot menu opens, inspect representative plots and stop its local server with `Ctrl+C` when finished. PNG generation can be slow, so enable `WRITE_PNG` only when PNG files are required.

## 5. Update float-log summaries when needed

```bat
cd /d C:\Users\athay\Documents\bgc_website\navis_logfile_parsing
.venv\Scripts\python.exe run_float_summaries.py
```

This reads from `Z:\bgc\data` and writes engineering outputs below `Z:\bgc\data\www\bgc\engineering`.

## 6. Verify the result

Check that `engineeringtable.html` opens, representative float folders contain `health_report.html` and plots, `by_parameter` contains the across-float plots, and maps or `bathymetry.html` exist when enabled. Review the console for request errors, missing directories, or failed floats.

Do not stage credentials, `.venv`, `.vscode`, temporary output, or unrelated files.

## 7. Commit and push

From the repository root, review the exact changes:

```bat
cd /d C:\Users\athay\Documents\bgc_website
git status
git diff --stat
git diff
```

Stage only the intended files, then commit:

```bat
git add navis\bgcwebsite.py UPDATE_WEBSITE.md
git commit -m "Update BGC engineering website"
```

If tracked generated files are intentionally part of the update, add them explicitly after reviewing them. Push the reviewed commit:

```bat
git log -1 --oneline
git push origin main
```

The configured remote is `https://github.com/atoutdoors/bgc_website.git`. Confirm the commit appears on GitHub after pushing.

## Troubleshooting

- If the network path is unavailable, reconnect the `Z:` drive in the same Windows session running the script.
- If a package is missing, run `navis\.venv\Scripts\python.exe -m pip install -r navis\requirements.txt`.
- Database requests, map generation, and PNG writing can take time; check the latest progress message before stopping the process.
- If Git shows unexpected files, do not use broad `git add .`; stage explicit paths instead.
