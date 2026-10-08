@echo off
setlocal DisableDelayedExpansion
set "labRoot=%~dp0"

if exist "%labRoot%.venv\Scripts\python.exe" (
    set "labPython=%labRoot%.venv\Scripts\python.exe"
) else if exist "%labRoot%.runtime\python\python.exe" (
    set "labPython=%labRoot%.runtime\python\python.exe"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python was not found. Install Python and the dependencies described in README.md.
        exit /b 1
    )
    set "labPython=python"
)

pushd "%labRoot%"
if errorlevel 1 exit /b 1
"%labPython%" "%labRoot%run_lab.py"
set "labExit=%ERRORLEVEL%"
popd
exit /b %labExit%
