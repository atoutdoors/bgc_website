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

echo.
echo Virtual environment is ready.
echo.
echo To run all float summaries:
echo     py run_float_summaries.py
echo.
echo To run one float parser directly:
echo     py float_log_summary.py
echo.
cmd /k
