@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating S2BGC Python virtual environment...
    py -m venv .venv
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        pause
        exit /b 1
    )
) else (
    echo S2BGC virtual environment already exists.
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip

echo.
echo Virtual environment is ready.
echo To activate it later, run:
echo     .venv\Scripts\activate.bat
echo.
echo To run the S2BGC batch script:
echo     python run_engineering_for_serials.py
echo.
echo Running the S2BGC engineering report generator...
python run_engineering_for_serials.py
if errorlevel 1 (
    echo The S2BGC report generator returned an error.
)
pause
