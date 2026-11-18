@echo off
setlocal

rem Usage:
rem   build_mission_paper_html.bat --overwrite
rem   build_mission_paper_html.bat --no-overwrite
rem   build_mission_paper_html.bat "D:\BGC\data" --no-overwrite

echo.
echo ========================================
echo   Navis mission paper builder
echo ========================================
echo.

rem Run this file from any directory; all paths are relative to this file.
set "SCRIPT_DIR=%~dp0"
set "SCRIPT=%SCRIPT_DIR%build_mission_paper_html.py"

if defined MISSION_DATA_ROOT (
    echo [1/4] Mission data folder: %MISSION_DATA_ROOT%
) else (
    echo [1/4] Mission data folder: Z:\bgc\data
)
if defined MISSION_PAPER_OUTPUT_DIR (
    echo [1/4] Paper output folder: %MISSION_PAPER_OUTPUT_DIR%
) else (
    echo [1/4] Paper output folder: Z:\www\bgc\engineering
)
echo [1/4] Overwrite mode: ON (use --no-overwrite to preserve the server copy)
echo %* | findstr /i /c:"--no-overwrite" >nul
if not errorlevel 1 echo [1/4] Overwrite mode: OFF (--no-overwrite)

rem Prefer a project-local environment, then Python on PATH, then the
rem Windows Python launcher. The local environment is optional.
if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    set PYTHON="%SCRIPT_DIR%.venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=python"
    ) else (
        where py >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON=py -3"
        ) else (
            set "PYTHON="
        )
    )
)

if not defined PYTHON (
    echo [2/4] Python was not found.
    echo Python 3 was not found.
    echo Install it from https://www.python.org/downloads/ and try again.
    pause
    exit /b 1
)

echo [2/4] Python found: %PYTHON%

%PYTHON% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)"
if errorlevel 1 (
    echo Python 3.8 or newer is required.
    %PYTHON% --version
    pause
    exit /b 1
)

pushd "%SCRIPT_DIR%"
echo [3/4] Generating mission-analysis CSV files and figures...
%PYTHON% -u "%SCRIPT%" %*
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" echo [4/4] HTML report generated successfully.
popd

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [4/4] Mission paper generation failed with exit code %EXIT_CODE%.
    pause
)

if "%EXIT_CODE%"=="0" (
    echo.
    echo Output: analysis_output\mission_analysis\navis_mission_changes_paper.html
)

exit /b %EXIT_CODE%
