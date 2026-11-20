@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
set "S2BGC=%ROOT%S2BGC"
set "PARSER=%ROOT%navis_logfile_parsing"
set "NAVIS=%ROOT%navis"
set "LOG_DIR=%ROOT%logs"
set "LOG=%LOG_DIR%\hourly-build.log"
set "SUCCESS_STATE=%LOG_DIR%\hourly-build-success-streak.txt"
set "LOCK_DIR=%TEMP%\bgc_website_hourly_build.lock"
set "BUILD_OK=1"

if not defined S2BGC_DATA_ROOT set "S2BGC_DATA_ROOT=Z:\S2BGC\data"
if not defined S2BGC_OUTPUT_DIR set "S2BGC_OUTPUT_DIR=Z:\www\bgc\engineering\S2BGC"
if not defined BGC_DATA_ROOT set "BGC_DATA_ROOT=Z:\bgc\data"
if not defined BGC_ENGINEERING_ROOT set "BGC_ENGINEERING_ROOT=Z:\www\bgc\engineering"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
if exist "%LOCK_DIR%" (
    echo Another hourly build is already running. Exiting.
    exit /b 2
)
mkdir "%LOCK_DIR%" >nul 2>&1
if errorlevel 1 (
    echo Another hourly build is already running. Exiting.
    exit /b 2
)

if not exist "%S2BGC%\.venv_runtime\Scripts\python.exe" (
    echo ERROR: Run S2BGC\setup_s2bgc_venv.bat first.
    set "BUILD_OK=0"
    goto :finish
)
if not exist "%PARSER%\.venv\Scripts\python.exe" (
    echo ERROR: Run navis_logfile_parsing\setup_float_parser_venv.bat first.
    set "BUILD_OK=0"
    goto :finish
)
if not exist "%NAVIS%\.venv\Scripts\python.exe" (
    echo ERROR: Run navis\setup_bgc_environment.bat first.
    set "BUILD_OK=0"
    goto :finish
)

echo ==== Build started %date% %time% ==== >> "%LOG%"
echo ================================================
echo       BGC WEBSITE HOURLY BUILD
echo ================================================
echo Log: %LOG%

call :progress 0 "Starting build"
call :progress 5 "S2BGC engineering pages"
powershell -NoProfile -Command "& { & '%S2BGC%\.venv_runtime\Scripts\python.exe' '%S2BGC%\run_engineering_for_serials.py' 2>&1 | Tee-Object -FilePath '%LOG%' -Append; exit $LASTEXITCODE }"
if errorlevel 1 call :failed "S2BGC engineering pages"

call :progress 30 "Navis float summaries"
powershell -NoProfile -Command "& { & '%PARSER%\.venv\Scripts\python.exe' '%PARSER%\run_float_summaries.py' --data-root '%BGC_DATA_ROOT%' 2>&1 | Tee-Object -FilePath '%LOG%' -Append; exit $LASTEXITCODE }"
if errorlevel 1 call :failed "Navis float summaries"

call :progress 55 "Main BGC website"
powershell -NoProfile -Command "& { & '%NAVIS%\.venv\Scripts\python.exe' -u '%NAVIS%\bgcwebsite.py' 2>&1 | Tee-Object -FilePath '%LOG%' -Append; exit $LASTEXITCODE }"
if errorlevel 1 call :failed "Main BGC website"

call :progress 80 "Mission paper HTML"
powershell -NoProfile -Command "& { & '%NAVIS%\.venv\Scripts\python.exe' -u '%NAVIS%\build_mission_paper_html.py' '%BGC_DATA_ROOT%' 2>&1 | Tee-Object -FilePath '%LOG%' -Append; exit $LASTEXITCODE }"
if errorlevel 1 call :failed "Mission paper HTML"

call :progress 100 "Build stages complete"

:finish
echo ==== Build finished %date% %time% ==== >> "%LOG%"
if "!BUILD_OK!"=="1" (
    set "SUCCESS_STREAK=0"
    if exist "%SUCCESS_STATE%" set /p SUCCESS_STREAK=<"%SUCCESS_STATE%"
    set /a SUCCESS_STREAK+=1
    echo !SUCCESS_STREAK!>"%SUCCESS_STATE%"
    if !SUCCESS_STREAK! GEQ 3 (
        type nul > "%LOG%"
        echo 3 consecutive successful builds. Log cleared.
        echo 0>"%SUCCESS_STATE%"
    )
) else (
    echo 0>"%SUCCESS_STATE%"
)
rd "%LOCK_DIR%" >nul 2>&1
echo Finished: %date% %time%
echo Details: %LOG%
if "!BUILD_OK!"=="1" (exit /b 0) else (exit /b 1)

:progress
set "PERCENT=%~1"
set "MESSAGE=%~2"
set /a FILLED=PERCENT/2
set "BAR="
for /L %%N in (1,1,50) do if %%N LEQ !FILLED! (set "BAR=!BAR!#") else (set "BAR=!BAR!-" )
powershell -NoProfile -Command "$s='[!BAR!] !PERCENT!%% - !MESSAGE! - %time%'; [Console]::Write(('`r' + $s.PadRight(120)))"
exit /b 0

:failed
set "BUILD_OK=0"
echo FAILED: %~1 %date% %time% >> "%LOG%"
echo FAILED: %~1
exit /b 0
