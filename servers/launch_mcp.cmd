@echo off
REM Cross-platform launcher for the improve MCP server (Windows).
REM
REM Only job: resolve a Python 3 interpreter and run mcp_server.py. The server
REM itself handles virtualenv creation, dependency installation, and in-process
REM venv activation on Windows -- see mcp_server.py for details.
REM
REM Used as the `command` in .claude-plugin/plugin.json so the plugin does not
REM hard-code `python3` (which is missing on many Windows installs).
REM Tries the `py` launcher first (bundled with python.org installs), then
REM `python`, then `python3`.

setlocal
set "DIR=%~dp0"

if defined IMPROVE_PYTHON (
    if not exist "%IMPROVE_PYTHON%" (
        echo improve: IMPROVE_PYTHON does not exist: %IMPROVE_PYTHON% 1>&2
        exit /b 1
    )
    "%IMPROVE_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo improve: IMPROVE_PYTHON must be Python 3.10+: %IMPROVE_PYTHON% 1>&2
        exit /b 1
    )
    "%IMPROVE_PYTHON%" "%DIR%mcp_server.py" %*
    exit /b
)

py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && goto use_py
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && goto use_python
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && goto use_python3

echo improve: Python 3.10+ interpreter not found (tried py -3, python, python3). 1>&2
exit /b 1

:use_py
py -3 "%DIR%mcp_server.py" %*
exit /b

:use_python
python "%DIR%mcp_server.py" %*
exit /b

:use_python3
python3 "%DIR%mcp_server.py" %*
exit /b
