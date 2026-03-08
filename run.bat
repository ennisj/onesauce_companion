@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if not defined PYTHONPATH (
    set "PYTHONPATH=%SCRIPT_DIR%src"
) else (
    set "PYTHONPATH=%SCRIPT_DIR%src;%PYTHONPATH%"
)

python -m onesauce_companion.app

