@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"

if not defined PYTHON_EXE if defined S2BGC_PYTHON if exist "%S2BGC_PYTHON%" set "PYTHON_EXE=%S2BGC_PYTHON%"

if not defined PYTHON_EXE (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python"
)

if not defined PYTHON_EXE (
    where py >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=py -3"
)

if not defined PYTHON_EXE (
    echo ERROR: No Python interpreter was found on PATH.
    echo Install Python 3 and rerun this script, or set S2BGC_PYTHON.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating S2BGC Python virtual environment with %PYTHON_EXE%...
    %PYTHON_EXE% -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create the virtual environment.
        exit /b 1
    )
)

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
"%VENV_PYTHON%" -m pip install --upgrade pip

echo.
echo Virtual environment is ready.
echo To activate it later, run:
echo     .venv\Scripts\activate.bat
echo.
echo To run the S2BGC batch script:
echo     .venv\Scripts\python.exe run_engineering_for_serials.py
echo.
echo Running the S2BGC engineering report generator...
"%VENV_PYTHON%" run_engineering_for_serials.py
if errorlevel 1 (
    echo The S2BGC report generator returned an error.
    exit /b 1
)

exit /b 0
