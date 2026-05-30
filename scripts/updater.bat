@echo off
setlocal

rem Argument 1 is the git branch to pull (default: main).
set BRANCH=%1
if "%BRANCH%"=="" set BRANCH=main

rem Project root is the parent of scripts/
cd /d "%~dp0.."

rem Log everything to updater.log so failures are debuggable (we run headlessly).
set LOG=%~dp0..\updater.log
echo. >> "%LOG%"
echo ============================================ >> "%LOG%"
echo %DATE% %TIME% - Updater start (branch=%BRANCH%) >> "%LOG%"
echo CWD=%CD% >> "%LOG%"

rem Wait for current CraftBot to fully terminate.
timeout /t 3 /nobreak > nul

echo --- git fetch --- >> "%LOG%"
git fetch origin %BRANCH% >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

echo --- git checkout --- >> "%LOG%"
git checkout %BRANCH% >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

echo --- git pull --- >> "%LOG%"
git pull origin %BRANCH% >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

if exist install.py (
    echo --- install.py --- >> "%LOG%"
    python install.py >> "%LOG%" 2>&1
    if errorlevel 1 goto :fail
)

echo --- relaunching CraftBot --- >> "%LOG%"
rem Launch the new CraftBot. This bat process exits and the new run.py takes over.
start "CraftBot" python run.py
echo %DATE% %TIME% - Updater done, relaunched CraftBot >> "%LOG%"
exit /b 0

:fail
echo %DATE% %TIME% - UPDATE FAILED, see above >> "%LOG%"
exit /b 1
