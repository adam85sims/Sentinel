@echo off
REM Sentinel WebUI — dev start script
REM Starts the FastAPI server for testing.
REM
REM Usage:
REM   start-webui.bat              — default (127.0.0.1:8090)
REM   start-webui.bat --port 3000  — custom port
REM
REM Note: --reload is not supported yet (uvicorn requires import string
REM for reload, but server.py builds the app inline). Restart manually
REM after code changes, or use the --reload flag once server.py is refactored.

setlocal

set "PROJECT_DIR=%~dp0"
set "VENV_PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
set "SCENARIO_DIR=%PROJECT_DIR%examples"

REM Check venv exists
if not exist "%VENV_PYTHON%" (
    echo ERROR: .venv not found at %PROJECT_DIR%.venv
    echo Run: uv sync --extra web
    exit /b 1
)

echo Starting Sentinel WebUI...
echo   Server:   http://127.0.0.1:8090
echo   API docs: http://127.0.0.1:8090/api/docs
echo   Scenarios: %SCENARIO_DIR%
echo.

"%VENV_PYTHON%" -m sentinel.web.server --port 8090 --scenario-dir "%SCENARIO_DIR%" %*

endlocal
