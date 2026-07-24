@echo off
REM Cross-platform hook launcher (Windows).
REM
REM Resolves a Python 3 interpreter and runs a hook script from scripts\.
REM Used by hooks\hooks.json so hooks do not hard-code `python3` (absent on
REM many Windows installs). Usage:  run_hook <script.py> [args...]
REM
REM Hook scripts use only the standard library, so no virtualenv is needed.
REM They share modules with the MCP server and require Python 3.10+.

setlocal
set "DIR=%~dp0"
set "SCRIPT=%~1"
shift /1

py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && goto use_py
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && goto use_python
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && goto use_python3

echo improve hook: Python 3.10+ interpreter not found (tried py -3, python, python3). 1>&2
exit /b 1

:use_py
py -3 "%DIR%%SCRIPT%" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b

:use_python
python "%DIR%%SCRIPT%" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b

:use_python3
python3 "%DIR%%SCRIPT%" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b
