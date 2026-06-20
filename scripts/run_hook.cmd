@echo off
REM Cross-platform hook launcher (Windows).
REM
REM Resolves a Python 3 interpreter and runs a hook script from scripts\.
REM Used by hooks\hooks.json so hooks do not hard-code `python3` (absent on
REM many Windows installs). Usage:  run_hook <script.py> [args...]
REM
REM Hook scripts use only the standard library, so any Python 3 will do — no
REM virtualenv is needed here (unlike servers\launch_mcp.cmd).

setlocal
set "DIR=%~dp0"
set "SCRIPT=%~1"
shift /1

where py >nul 2>&1 && (
    py "%DIR%%SCRIPT%" %1 %2 %3 %4 %5 %6 %7 %8 %9
    exit /b %ERRORLEVEL%
)
where python >nul 2>&1 && (
    python "%DIR%%SCRIPT%" %1 %2 %3 %4 %5 %6 %7 %8 %9
    exit /b %ERRORLEVEL%
)
where python3 >nul 2>&1 && (
    python3 "%DIR%%SCRIPT%" %1 %2 %3 %4 %5 %6 %7 %8 %9
    exit /b %ERRORLEVEL%
)

echo 4-fire hook: Python 3 interpreter not found (tried py, python, python3). 1>&2
exit /b 1
