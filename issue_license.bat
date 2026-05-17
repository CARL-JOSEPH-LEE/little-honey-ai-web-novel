@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

pushd "%~dp0"

if not exist "seller_private_key.json" (
    echo [ERROR] seller_private_key.json not found in current directory.
    echo         Place this bat next to seller_private_key.json.
    goto :end_error
)

if not exist "novel_writer\license_admin.py" (
    echo [ERROR] novel_writer\license_admin.py not found.
    echo         Place this bat in the project root.
    goto :end_error
)

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"

where %PYTHON_EXE% >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ and put it on PATH.
    goto :end_error
)

if "%~1"=="" (
    "%PYTHON_EXE%" -m novel_writer.license_admin issue-activation-code
) else if "%~2"=="" (
    "%PYTHON_EXE%" -m novel_writer.license_admin issue-activation-code "%~1"
) else (
    "%PYTHON_EXE%" -m novel_writer.license_admin issue-activation-code "%~1" "%~2"
)
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" goto :end_error

start "" explorer "activation-codes"
goto :end_ok

:end_error
set "RC=1"
goto :end_finally

:end_ok
set "RC=0"
goto :end_finally

:end_finally
echo.
if "%~1"=="" pause
popd
endlocal & exit /b %RC%
