@echo off
setlocal

rem Create the environment in whichever directory this file is run from.
set "ENV_DIR=%CD%\.venv"

echo.
echo WHOI BGC Python environment setup
echo Target directory: %CD%
echo Virtual environment: %ENV_DIR%
echo.

rem Prefer the Windows Python launcher when it is available.
where py >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON=py -3"
) else (
    set "PYTHON=python"
)

%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo Python was not found.
    echo Install Python 3 from https://www.python.org/downloads/ and try again.
    pause
    exit /b 1
)

if not exist "%ENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON% -m venv "%ENV_DIR%"
    if errorlevel 1 (
        echo Could not create the virtual environment.
        pause
        exit /b 1
    )
) else (
    echo Existing virtual environment found; updating it.
)

echo Installing Python packages...
"%ENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
"%ENV_DIR%\Scripts\python.exe" -m pip install --upgrade pandas plotly requests openpyxl kaleido
if errorlevel 1 (
    echo Package installation failed.
    pause
    exit /b 1
)

echo Verifying installed packages...
"%ENV_DIR%\Scripts\python.exe" -c "import pandas, plotly, requests, openpyxl, kaleido; from plotly.colors import sample_colorscale; print('pandas', pandas.__version__); print('plotly', plotly.__version__); print('Turbo colormap:', sample_colorscale('Turbo', [0, 1]))"
if errorlevel 1 (
    echo Package verification failed.
    pause
    exit /b 1
)

echo.
echo Setup complete.
echo.
echo To activate this environment in Command Prompt:
echo     .venv\Scripts\activate
echo.
echo To run the BGC script without activating it:
echo     .venv\Scripts\python.exe bgcwebsite.py
echo.
pause
