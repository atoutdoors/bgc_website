# BGC Website Hourly Build

## Merging branch

`run_all_hourly.bat` is the main entry point for the `merging` branch. It runs the complete website update:

1. S2BGC engineering pages
2. Navis float summaries
3. The main BGC website
4. Mission-paper HTML

Run it from the repository root:

```bat
cd /d C:\Users\athay\Documents\bgc_website
run_all_hourly.bat
```

You can also double-click `run_all_hourly.bat` in File Explorer. The batch file resolves its source and log paths relative to its own location.

## First-time setup

On a new or repaired computer, run these setup files once from the repository root:

```bat
S2BGC\setup_s2bgc_venv.bat
navis_logfile_parsing\setup_float_parser_venv.bat
navis\setup_bgc_environment.bat
```

After setup, use only `run_all_hourly.bat` for the complete production build. It checks that the required Python environments exist before starting.

## Data paths

The default data paths use the `Z:\` drive. Before running on another computer, set these environment variables to accessible local or UNC paths:

```bat
set S2BGC_DATA_ROOT=Z:\S2BGC\data
set S2BGC_OUTPUT_DIR=Z:\www\bgc\engineering\S2BGC
set BGC_DATA_ROOT=Z:\bgc\data
set BGC_ENGINEERING_ROOT=Z:\www\bgc\engineering
```

For scheduled tasks, mapped drives such as `Z:\` may not be available. Use UNC paths such as `\\server\share\folder` instead. In Task Scheduler, use the full path to `run_all_hourly.bat` and set **Start in** to the repository folder.

## Logs and behavior

- Live output and the latest build details: `logs\hourly-build.log`
- S2BGC diagnostics: `S2BGC\s2bgc_engineering_run.log`
- Navis summary diagnostics: `navis_logfile_parsing\float_summary_run.log`
- A lock at `%TEMP%\bgc_website_hourly_build.lock` prevents overlapping builds.
- The log is cleared after three consecutive successful builds.
- A failed stage makes the batch file return a failure exit code.
- Engineering tables and browser windows are not opened automatically.

If a run fails, start with `logs\hourly-build.log` and the stage-specific diagnostic log. If the lock remains after confirming no build is running, remove that exact lock folder before retrying.

## Updating the branch

From the repository root:

```bat
git status
git pull origin merging
```

Review changes before committing. Do not stage virtual environments, credentials, temporary output, or unrelated generated files.
