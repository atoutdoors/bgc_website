@echo off
setlocal

cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=py"
) else (
    where python >nul 2>&1
    if not %errorlevel%==0 (
        echo Python was not found. Install Python 3 and try again.
        pause
        exit /b 1
    )
    set "PYTHON_CMD=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON_CMD% -m venv .venv
    if not %errorlevel%==0 (
        echo Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

rem Prefer the mapped network drive when it is available. If it is not
rem available, leave BGC_DATA_ROOT unset so the Python launcher can try its
rem configured UNC fallback. Override this before running for another share.
if not defined BGC_DATA_ROOT if exist "Z:\bgc\data\" set "BGC_DATA_ROOT=Z:\bgc\data"
if not defined BGC_ENGINEERING_ROOT set "BGC_ENGINEERING_ROOT=Z:\www\bgc\engineering"

echo.
echo Data root:       %BGC_DATA_ROOT%
echo Engineering root: %BGC_ENGINEERING_ROOT%
if defined BGC_DATA_ROOT if not exist "%BGC_DATA_ROOT%" (
    echo.
    echo WARNING: The configured data path is not available.
    echo Verify the share is connected, or override BGC_DATA_ROOT with the UNC path.
)
if not defined BGC_DATA_ROOT (
    echo No mapped Z: data drive detected; the launcher will try its UNC fallback.
)

echo.
echo Virtual environment is ready.
echo.
echo To run all float summaries:
echo     python run_float_summaries.py
echo.
echo To use a different data share:
echo     set BGC_DATA_ROOT=\\server\share\bgc\data
echo     python run_float_summaries.py
echo.
echo To run one float parser directly:
echo     python float_log_summary.py
echo.
cmd /k
