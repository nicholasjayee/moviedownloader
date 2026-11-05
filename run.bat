@echo off
setlocal

rem Use the shared Python launcher for automatic IP detection, ports, and --dev.
pushd "%~dp0" || exit /b 1

where uv >nul 2>&1
if errorlevel 1 (
    echo Error: uv is required to run Moviebox. 1>&2
    popd
    exit /b 1
)

call uv run python main.py %*
set "MOVIEBOX_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %MOVIEBOX_EXIT_CODE%
