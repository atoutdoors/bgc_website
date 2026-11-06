@echo off
setlocal

cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python was not found. Install Python 3 and try again.
        pause
        exit /b 1
    )
    set "PYTHON_CMD=python"
) else (
    set "PYTHON_CMD=py -3"
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

echo Using:
python -c "import sys; print(sys.executable)"

echo.
echo Virtual environment is ready.
echo.
echo To run all float summaries:
echo     python run_float_summaries.py
echo.
echo To run one float parser directly:
echo     python float_log_summary.py
echo.
cmd /k
