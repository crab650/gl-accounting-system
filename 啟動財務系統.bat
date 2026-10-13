@echo off
setlocal
cd /d "%~dp0" || goto :error

set "APP_PYTHON="
set "APP_ARGS="
set "BASE_PYTHON=python"
set "BASE_ARGS="
python -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
if errorlevel 1 (
    py -3 -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
    if not errorlevel 1 (
        set "BASE_PYTHON=py"
        set "BASE_ARGS=-3"
    )
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys, flask, flask_sqlalchemy, flask_migrate; assert sys.version_info >= (3, 11)" >nul 2>&1
    if not errorlevel 1 set "APP_PYTHON=%CD%\.venv\Scripts\python.exe"
)

if not defined APP_PYTHON (
    if exist ".deps" set "PYTHONPATH=%CD%\.deps;%PYTHONPATH%"
    "%BASE_PYTHON%" %BASE_ARGS% -c "import sys, flask, flask_sqlalchemy, flask_migrate; assert sys.version_info >= (3, 11)" >nul 2>&1
    if not errorlevel 1 (
        set "APP_PYTHON=%BASE_PYTHON%"
        set "APP_ARGS=%BASE_ARGS%"
    )
)

if not defined APP_PYTHON (
    "%BASE_PYTHON%" %BASE_ARGS% -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
    if errorlevel 1 (
        echo Python 3.11 or newer is required.
        goto :error
    )
    if not exist ".venv\Scripts\python.exe" (
        echo Creating local Python environment...
        "%BASE_PYTHON%" %BASE_ARGS% -m venv .venv || goto :error
    )
    echo Installing project dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
    set "APP_PYTHON=%CD%\.venv\Scripts\python.exe"
)

"%APP_PYTHON%" %APP_ARGS% scripts\start_local.py %*
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Startup failed. Check the message above.
pause
exit /b 1
