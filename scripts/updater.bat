@echo off
setlocal

rem Argument 1 is the git branch to pull (default: main).
set "BRANCH=%~1"
if "%BRANCH%"=="" set BRANCH=main

rem Argument 2 is the Python executable that launched CraftBot.
set "PYTHON_BIN=%~2"
if "%PYTHON_BIN%"=="" set PYTHON_BIN=python

rem Project root is the parent of scripts/
cd /d "%~dp0.."

rem Log everything to updater.log so failures are debuggable (we run headlessly).
set "LOG=%~dp0..\updater.log"
echo. >> "%LOG%"
echo ============================================ >> "%LOG%"
echo %DATE% %TIME% - Updater start (branch=%BRANCH%) >> "%LOG%"
echo CWD=%CD% >> "%LOG%"
echo Python=%PYTHON_BIN% >> "%LOG%"

rem Wait for current CraftBot to fully terminate.
timeout /t 3 /nobreak > nul

echo --- git fetch --- >> "%LOG%"
git fetch origin "%BRANCH%" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

rem The user's runtime files. They used to be tracked, so an edited copy (API
rem keys, memory) made `git pull` refuse to update. They are untracked now;
rem this carries the user's copies across the pull that untracks them, and is
rem a no-op on every pull after it.
set "RUNTIME_FILES=app\config\settings.json app\config\mcp_config.json app\config\scheduler_config.json app\config\skills_config.json agent_file_system\MEMORY.md agent_file_system\ENTITIES.md agent_file_system\PROACTIVE.md"
set "KEEP_DIR=%CD%\.update-keep"
echo --- keeping runtime files --- >> "%LOG%"
rem The file names are unique, so the backup folder is flat.
if exist "%KEEP_DIR%" rmdir /s /q "%KEEP_DIR%"
mkdir "%KEEP_DIR%"
for %%F in (%RUNTIME_FILES%) do (
    if exist "%%F" copy /y "%%F" "%KEEP_DIR%\%%~nxF" > nul
    git ls-files --error-unmatch "%%F" > nul 2>&1 && git checkout -- "%%F" >> "%LOG%" 2>&1
)

echo --- git checkout --- >> "%LOG%"
git checkout "%BRANCH%" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

echo --- git pull --- >> "%LOG%"
git pull --ff-only origin "%BRANCH%" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
call :restore

if exist install.py (
    echo --- install.py --- >> "%LOG%"
    "%PYTHON_BIN%" install.py >> "%LOG%" 2>&1
    if errorlevel 1 goto :fail
)

echo --- relaunching CraftBot --- >> "%LOG%"
rem Launch the new CraftBot. This bat process exits and the new run.py takes over.
start "CraftBot" "%PYTHON_BIN%" run.py --conda
echo %DATE% %TIME% - Updater done, relaunched CraftBot >> "%LOG%"
exit /b 0

:fail
call :restore
echo %DATE% %TIME% - UPDATE FAILED, see above >> "%LOG%"
exit /b 1

:restore
if not exist "%KEEP_DIR%" exit /b 0
for %%F in (%RUNTIME_FILES%) do (
    if exist "%KEEP_DIR%\%%~nxF" (
        if not exist "%%~dpF" mkdir "%%~dpF"
        copy /y "%KEEP_DIR%\%%~nxF" "%%F" > nul
    )
)
rmdir /s /q "%KEEP_DIR%"
exit /b 0
