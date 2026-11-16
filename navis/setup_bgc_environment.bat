@echo off
setlocal

rem Create the environment in whichever directory this file is run from.
set "ENV_DIR=%CD%\.venv"

echo.
echo WHOI BGC Python environment setup
echo Target directory: %CD%
echo Virtual environment: %ENV_DIR%
echo.

rem Use the Python command on PATH first. This works with Python 3.8 through
rem newer Python 3 releases and does not assume a particular install folder.
where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python"
) else (
    rem Fall back to the Windows Python launcher when python.exe is not on PATH.
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=py -3"
    ) else (
        set "PYTHON="
    )
)

if not defined PYTHON (
    echo Python was not found.
    echo Install Python 3 from https://www.python.org/downloads/ and try again.
    pause
    exit /b 1
)

%PYTHON% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)"
if errorlevel 1 (
    echo Python 3.8 or newer is required.
    %PYTHON% --version
    pause
    exit /b 1
)

rem A copied or removed base Python can leave an unusable old venv behind.
rem Recreate only this project's generated environment when that happens.
if exist "%ENV_DIR%\Scripts\python.exe" (
    "%ENV_DIR%\Scripts\python.exe" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo Existing virtual environment is invalid; recreating it...
        rmdir /s /q "%ENV_DIR%"
    )
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
"%ENV_DIR%\Scripts\python.exe" -m pip install --upgrade -r "%~dp0requirements.txt"
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
