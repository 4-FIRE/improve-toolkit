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
    "%IMPROVE_PYTHON%" "%DIR%mcp_server.py" %*
    exit /b %ERRORLEVEL%
)

where py >nul 2>&1 && (
    py "%DIR%mcp_server.py" %*
    exit /b %ERRORLEVEL%
)
where python >nul 2>&1 && (
    python "%DIR%mcp_server.py" %*
    exit /b %ERRORLEVEL%
)
where python3 >nul 2>&1 && (
    python3 "%DIR%mcp_server.py" %*
    exit /b %ERRORLEVEL%
)

echo improve: Python 3 interpreter not found (tried py, python, python3). 1>&2
exit /b 1
